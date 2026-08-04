# Agent 功能与实现说明

本文整理项目中“Agent 生成”和“Agent 续写改编”的功能边界、执行流程、Session 持久化、前后端入口与扩展方式。内容以当前代码实现为准。

## 1. 功能总览

| 模式 | Session mode | 前端路由 | 作用 |
|------|--------------|----------|------|
| Agent 生成 | `generate` | `/projects/:projectId/agent` | 从一句想法生成结构化蓝图，并创建项目资料、大纲、人物、场景、章节及部分正文 |
| Agent 续写改编 | `continue_edit` | `/projects/:projectId/agent-continue` | 让 LLM 基于已有章节生成可执行 Plan，再复用小说 AI 生成和 AI 打磨逐步执行 |

两个模式都要求用户先创建并进入一个项目。Agent 不创建最外层 `Project` 记录，只在当前项目范围内工作。

共同能力：

- 先由 LLM 生成结构化 Plan，持久化后等待用户确认；
- 只有用户点击确认后，才会创建或修改项目内容；
- 通过 SSE 将计划、待执行步骤、当前步骤、进度和结果实时返回前端；
- 通过 Agent Session 持久化请求、Plan、最终步骤、结果和错误；
- Session 默认名称等于 Session ID，可在页面重命名、切换、新建或删除；
- Session 与项目和模式绑定，不能跨项目或跨模式复用。

## 2. 总体调用链

```mermaid
flowchart TD
    UI[Agent 页面] --> SESSION[创建或复用 Session]
    SESSION --> START[标记 planning 并清空该 Session 上次运行数据]
    START --> LLM[LLM 生成结构化 Plan]
    LLM --> SAVE_PLAN[持久化 Plan 并标记 awaiting_confirmation]
    SAVE_PLAN --> CONFIRM{用户确认?}
    CONFIRM -->|重新规划| START
    CONFIRM -->|确认| EXECUTE[标记 running 并按计划执行]
    EXECUTE --> EVENTS[SSE 实时发送步骤与结果]
    EVENTS --> FINISH{执行结果}
    FINISH -->|成功| COMPLETE[持久化 completed、steps、result]
    FINISH -->|失败| FAILED[持久化 failed、steps、error 和可用的部分结果]
```

当前 Session 是运行记录，不是后台任务队列。浏览器刷新后可以读取已经持久化的 Plan 和结果，但不能重新订阅已经断开的执行流，也不支持从中断步骤自动续跑。

## 3. Agent 生成

### 3.1 接口

前端使用流式接口：

```http
POST /api/v1/projects/{project_id}/novel-agent/write-stream
```

该接口只生成蓝图并进入等待确认状态。确认执行使用：

```http
POST /api/v1/projects/{project_id}/novel-agent/write-execute-stream
```

确认请求体为 `{"session_id":"..."}`。确认前不会更新项目信息，也不会创建大纲、人物、场景、章节或正文。

同步兼容接口：

```http
POST /api/v1/projects/{project_id}/novel-agent/write
```

请求中的 `session_id` 可省略。省略时后端自动创建 `mode=generate` 的 Session；传入时只接受当前项目中相同模式的 Session。

### 3.2 蓝图生成

服务读取以下系统设置并调用 LLM JSON Object 模式：

- `novel_agent.blueprint_system`
- `novel_agent.blueprint_user_template`
- `novel_agent.blueprint_temperature`

用户模板会注入创意、题材、文风、额外要求、卷数、章节数和目标总字数。普通模型的蓝图输出预算为 32768 tokens；DeepSeek 官方 V4 接口会自动使用当前文档标明的最大输出预算 384K（393216 tokens），不再受 LLM 配置中较小的默认 `max_tokens` 限制。

依据：

- [DeepSeek 模型 & 价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing)：V4 上下文长度 1M，最大输出 384K；
- [DeepSeek Responses API](https://api-docs.deepseek.com/zh-cn/guides/responses_api)：支持 `max_output_tokens`，但不支持 `previous_response_id` 和 `conversation`，接口为无状态调用。

蓝图的主要结构包括：

```json
{
  "project": {},
  "style_guide": "正文风格指南",
  "outline": { "children": [] },
  "characters": [],
  "scenes": [],
  "agent_plan": []
}
```

程序至少要求 `project` 和 `outline` 为 JSON 对象。返回内容会依次尝试直接解析、移除 Markdown 代码围栏后解析，以及从混合文本中截取完整 JSON 对象。

Session 的 `plan` 保存完整蓝图，而不仅是蓝图内部的 `agent_plan`。

### 3.3 固定执行步骤

`NovelAgentService.write_from_idea_stream()` 按以下顺序执行：

1. `plan_blueprint`：蓝图生成；
2. `create_project`：可选更新项目名称、简介、题材、目标字数和设置；
3. `create_outline`：创建分卷分章大纲树；
4. `create_characters`：创建人物档案；
5. `create_scenes`：创建场景卡片；
6. `create_chapters`：按大纲章节节点创建章节草稿；
7. `write_chapters`：复用 `ChapterService.novel_write()` 生成前 N 章正文。

蓝图中的 `agent_plan` 是规划信息，当前不会改变上述后端执行顺序。

### 3.4 写入规则

- 每次运行都会新建一份大纲，不覆盖已有大纲；
- 人物、场景和章节会追加到当前项目，不自动去重；
- `chapter_count` 表示全书所有卷合计生成的章节总数，不是每卷章数；各卷可按剧情需要分配不同数量的章节，蓝图会校验卷数与总章数；
- `write_chapter_count=0` 时只生成结构，不生成正文；
- `update_project=false` 只跳过项目元信息更新，不影响其他资源创建；
- 正文写作复用现有大纲、人物、场景、前文和文风上下文。

最终 `result` 保存项目、大纲、人物、场景、当前章节列表、已生成正文的章节、蓝图和步骤。

## 4. Agent 续写改编

### 4.1 接口与上下文

```http
POST /api/v1/projects/{project_id}/novel-agent/continue-stream
```

该接口只生成续写改编 Plan。用户确认后调用：

```http
POST /api/v1/projects/{project_id}/novel-agent/continue-execute-stream
```

确认请求体为 `{"session_id":"..."}`。确认前不会创建缺失的章节记录或章节版本快照，也不会生成、打磨或覆盖任何章节正文。

该模式只操作当前项目已有章节记录，以及大纲中已经规划但尚未创建章节记录的 `CHAPTER` 节点；不会创建项目、大纲、人物、场景，也不会编造大纲之外的新章节。每次生成 Plan 都会重新从数据库同步当前项目，而不是使用 Session 中保存的旧上下文。LLM 会收到：

- 项目简介、题材、状态、目标字数和项目设定；
- 完整大纲及节点层级、摘要、顺序和元数据；
- 可供 AI 使用的人物档案与人物关系；
- 当前场景库；
- 按大纲和章节真实顺序排列的目标 ID、标题、摘要、大纲节点、状态、字数、是否空白和最多 2000 字的正文尾部摘录；
- 已写/空白章节数量及对应目标 ID。已有章节记录使用真实 UUID，尚未实例化的大纲章节使用 `outline-node:<大纲节点 ID>` 临时目标 ID。

人物的 `setting_collection` 属于不提供给 AI 的私密设定，不会进入 Plan 或章节执行上下文。

### 4.2 Plan 设置与结构

使用以下系统设置：

- `novel_agent.continue_plan_system`
- `novel_agent.continue_plan_user_template`
- `novel_agent.continue_plan_temperature`

标准 Plan：

```json
{
  "summary": "本次续写改编计划摘要",
  "actions": [
    {
      "action": "write",
      "chapter_id": "真实章节 ID",
      "instruction": "本步骤的具体要求",
      "style_requirements": "可选文风要求",
      "include_previous_chapter": false,
      "include_next_chapter": false
    },
    {
      "action": "polish",
      "chapter_id": "真实章节 ID",
      "instruction": "加强人物动机并收紧节奏",
      "style_requirements": null,
      "include_previous_chapter": true,
      "include_next_chapter": false
    }
  ]
}
```

后端会规范化和校验 Plan：

- 只允许 `write`、`polish` 两种动作；
- `chapter_id` 必须来自当前项目，可以是已有章节 UUID 或 `outline-node:<大纲节点 ID>` 临时目标；编造或跨项目 ID 会被丢弃；
- 动作数量最多为请求的 `max_actions`；
- “连续续写”“多个章节”或明确章节数量的要求会按章节拆成多个 `write` 动作并按章节顺序执行；
- 对“剩余/余下/其余/全部/所有空白章节”以及明确数量的空白章节要求，后端会同时检查已有章节正文和未实例化的大纲 `CHAPTER` 节点，并直接解析 `resolved_targets`，不让 LLM 猜测目标章节；
- 如果模型首版 Plan 未覆盖作者明确要求的动作数量，服务会自动追加一次纠正规划；
- 即使纠正规划仍然漏章或错章，后端也会按 `resolved_targets` 补齐、去重并恢复为数据库章节顺序，且不会误选已有正文的章节；
- 缺少具体指令时补入默认执行要求；
- 规范化后没有合法动作则终止流程并记录失败。

### 4.3 执行动作

| Plan action | 复用能力 | 行为 |
|-------------|----------|------|
| `write` | `ChapterService.novel_write()` | 为已有章节生成或重写完整正文；若目标是未实例化的大纲章节，则在确认执行后先创建章节记录，再保留大纲节点摘要、合并动作指令并同步完整上下文 |
| `polish` | `ChapterService.novel_polish()` | 按动作指令打磨现有正文，同时注入当前项目、大纲、人物关系和场景参考，可选择参考前一章和后一章 |

用户确认后，服务才会把 Plan 中的 `outline-node:` 临时目标实例化为真实章节记录并替换为章节 UUID。每个动作开始前都会调用 `ChapterService.save_version()` 保存当前章节快照，`change_summary` 中记录 Session ID。因此，即使改编结果不满意，也可以使用已有章节版本能力恢复或对比原文。

动作按 Plan 顺序串行执行，并采用主从 Agent 模型：续写 Session 是主 Agent，负责生成 Plan 和调度；每个章节动作都会创建新的 `worker_session_id`，由一个无状态章节 Agent 重新从数据库构造该章所需的大纲、人物、场景、前文和动作要求，然后发起独立 LLM 请求。章节 Agent 之间不传递消息历史，也不复用上一章的模型会话上下文；需要的连续性只通过已落库章节和受控摘要进入下一章。

DeepSeek 章节 Agent 的 `write`、`polish` 输出预算同样自动提升到官方最大 384K；其他模型继续使用原有的 16384 tokens，避免向未知模型发送超过其能力的参数。

每完成一个动作，SSE 会发送 `action_result`，包含章节、字数、内容、备份版本 ID 和独立章节 Agent 的 `worker_session_id`；全部完成后写入 Session 的最终 `result`。

## 5. Agent Session

### 5.1 数据模型

表名为 `novel_agent_sessions`：

| 字段 | 用途 |
|------|------|
| `id` | UUID Session ID |
| `project_id` | 所属项目，项目删除时级联删除 Session |
| `mode` | `generate` 或 `continue_edit` |
| `name` | 显示名称；未提供时默认等于 `id` |
| `status` | `idle`、`planning`、`awaiting_confirmation`、`running`、`completed`、`failed` |
| `request_payload` | 最近一次运行的请求参数，不保存 `session_id` |
| `plan` | LLM 生成并经过校验的蓝图或续写 Plan |
| `steps` | 最近一次运行结束时的步骤状态 |
| `result` | 完整结果；续写失败时可保存已经完成的部分动作 |
| `error_message` | 最近一次失败信息 |
| `created_at` / `updated_at` | 创建和更新时间 |

同一个 Session 再次运行时会覆盖该 Session 的请求、Plan、步骤、结果和错误。若要保留多次独立运行历史，应先点击“新建会话”。删除 Session 只删除运行记录，不删除已生成或已修改的项目内容。

### 5.2 CRUD 接口

```http
GET    /api/v1/projects/{project_id}/novel-agent/sessions?mode=generate
POST   /api/v1/projects/{project_id}/novel-agent/sessions
GET    /api/v1/projects/{project_id}/novel-agent/sessions/{session_id}
PUT    /api/v1/projects/{project_id}/novel-agent/sessions/{session_id}
DELETE /api/v1/projects/{project_id}/novel-agent/sessions/{session_id}
```

创建请求：

```json
{ "mode": "continue_edit", "name": null }
```

重命名请求：

```json
{ "name": "第二卷节奏调整" }
```

Session 列表按 `updated_at`、`created_at` 倒序返回，两个 Agent 页面各自只查询自己的 mode。

## 6. SSE 事件

所有流式事件均为：

```text
data: {"type":"...", ...}
```

| type | Agent 生成 | Agent 续写改编 | 含义 |
|------|------------|----------------|------|
| `session` | ✓ | ✓ | 本次使用的 Session；省略 `session_id` 时前端由此获得新 ID |
| `steps` | ✓ | ✓ | 初始化或替换完整步骤列表 |
| `step` | ✓ | ✓ | 更新单个步骤的状态、消息及 `current/total` 进度 |
| `plan` | ✓ | ✓ | 返回结构化蓝图或续写 Plan；在随后发送 `confirmation_required` 前完成持久化 |
| `confirmation_required` | ✓ | ✓ | Plan 已持久化，Session 已进入 `awaiting_confirmation`，前端应展示确认按钮 |
| `action_result` | - | ✓ | 单个 `write` 或 `polish` 动作结果，含独立 `worker_session_id` |
| `result` | ✓ | ✓ | 最终结果，发送前已持久化 |
| `done` | ✓ | ✓ | 流程正常结束 |
| `error` | ✓ | ✓ | 流程失败；错误同时写入 Session |

SSE 响应开始后 HTTP 状态已经是 200，执行期错误通过 `type=error` 返回。前端按 `step.step` 合并步骤状态并实时展示大纲生成、人物生成、场景生成、内容生成或章节动作。

## 7. 提交与失败边界

计划阶段只写 Agent Session，不修改小说项目。用户确认后，Agent 生成先提交项目结构，之后每章正文由 `novel_write()` 单独提交。因此正文阶段失败时，已经创建的大纲、人物、场景、章节草稿和已完成正文会保留。

Agent 续写改编中，每次版本备份、`novel_write()` 和 `novel_polish()` 都会各自提交。后续动作失败不会回滚前面已完成的章节；Session 会标记为 `failed` 并持久化已完成动作的部分结果。

当前不提供跨完整 Agent 运行的原子事务，也不自动删除部分成功的数据。

## 8. 前端行为

两个页面共享 `AgentSessionBar`，提供：

- Session 列表和状态；
- 新建、切换、重命名和删除；
- Session ID 显示；
- 历史 Plan、步骤和结果恢复。

页面通过 `fetch` 读取 SSE，无固定请求超时。运行时禁用 Session 切换和表单操作；刷新页面后从 Session 接口恢复已经落库的数据。切换项目时会重新读取该项目的 Session，不复用上一项目状态。

## 9. 代码入口

| 层级 | 文件 | 职责 |
|------|------|------|
| 前端路由 | `frontend/src/App.tsx` | 注册两个 Agent 页面 |
| 工作区导航 | `frontend/src/modules/workspace/ProjectWorkspace.tsx` | 展示“Agent 生成”和“Agent 续写改编” |
| Agent 生成页面 | `frontend/src/modules/agent/NovelAgent.tsx` | 参数、SSE 步骤、蓝图与结果展示 |
| 续写改编页面 | `frontend/src/modules/agent/AgentContinue.tsx` | 改编要求、Plan、动作与结果展示 |
| Session 组件 | `frontend/src/modules/agent/AgentSessionBar.tsx` | 会话选择、新建、重命名和删除 |
| API 路由 | `backend/app/api/v1/novel_agent.py` | Session CRUD、同步生成和两个 SSE 入口 |
| Session 模型 | `backend/app/models/agent_session.py` | `novel_agent_sessions` 表 |
| Session 服务 | `backend/app/services/novel_agent_session_service.py` | 会话生命周期和结果持久化 |
| 生成服务 | `backend/app/services/novel_agent_service.py` | 蓝图生成及项目资源编排 |
| 续写服务 | `backend/app/services/novel_agent_continue_service.py` | Plan 生成、校验、备份和动作执行 |
| Prompt | `backend/app/llm/prompts/novel_agent.py` | 两类 Plan 的默认提示词 |
| 章节能力 | `backend/app/services/chapter_service.py` | 版本快照、小说 AI 生成和 AI 打磨 |
| Schema | `backend/app/schemas/novel_agent.py` | 请求、Session 和结果结构 |
| 集成测试 | `backend/tests/test_api.py` | Session、SSE、续写生成和打磨流程 |

## 10. 测试

PowerShell：

```powershell
cd backend
$env:DEBUG = "false"
python -m pytest tests/test_api.py -k novel_agent -q
```

前端：

```powershell
cd frontend
npm run build
```

扩展新的续写动作时，需要同时修改续写 Prompt、Plan 规范化校验、动作分派、前端动作类型和集成测试；只修改 Prompt 不会让后端获得新的可执行工具。
