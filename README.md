# 文脉工坊（Narrative Forge）— 启动与使用说明

## 1. 环境要求

| 依赖 | 最低版本 | 说明 |
|------|----------|------|
| Python | 3.11+ | 后端运行环境 |
| Node.js | 18+ | 前端运行环境 |
| npm | 9+ | 前端包管理器 |
| Git | 2.x | 版本控制（可选） |

---

## 2. 项目结构

```
narrative-forge/
├── backend/                 # 后端（Python / FastAPI）
│   ├── app/                 # 应用源码
│   │   ├── api/v1/          # API 路由
│   │   ├── core/            # 核心配置、安全、异常
│   │   ├── models/          # SQLAlchemy 数据模型
│   │   ├── schemas/         # Pydantic 请求/响应模式
│   │   ├── services/        # 业务逻辑层
│   │   ├── llm/             # LLM 集成（Provider、Prompt、频率限制）
│   │   ├── db/              # 数据库会话与初始化
│   │   └── main.py          # FastAPI 入口
│   ├── tests/               # 单元测试
│   ├── .env.example         # 环境变量示例；本地 .env 不提交
│   ├── data/                # 本地 SQLite/上传目录；仅保留空目录占位
│   └── pyproject.toml       # Python 项目配置
├── frontend/                # 前端（React / TypeScript / Vite）
│   ├── src/                 # 前端源码
│   │   ├── components/ui/   # 通用 UI 组件
│   │   ├── modules/         # 功能模块页面
│   │   ├── stores/          # Zustand 状态管理
│   │   ├── services/        # API 调用层
│   │   ├── types/           # TypeScript 类型定义
│   │   └── utils/           # 工具函数
│   └── package.json         # 前端依赖配置
└── docs/                    # 项目文档
```

> 开源副本不包含本地数据库、上传图片、日志、`.env` 或任何用户小说内容。详见 [OPEN_SOURCE.md](OPEN_SOURCE.md)。

> Windows 单文件 exe 构建与运行说明见 [WINDOWS_EXE.md](WINDOWS_EXE.md)。

---

## 3. 后端启动

> 下文中的 `cd backend` / `cd frontend` 都以本目录 `narrative-forge` 为起点。如果你当前位于完整仓库 `Novel_Writing_Agent` 根目录，请先执行：
>
> ```powershell
> cd open_source_release/narrative-forge
> ```
>
> 仓库根目录也有一套同名的 `backend` 和 `frontend`，直接从仓库根目录执行 `cd frontend` 会启动另一套前端，其中不包含本开源副本的新功能。

### 3.1 安装依赖

```bash
cd backend
pip install fastapi uvicorn sqlalchemy aiosqlite alembic httpx pydantic pydantic-settings cryptography python-dotenv aiofiles websockets
```

或使用项目配置安装：

```bash
cd backend
pip install -e .
```

### 3.2 配置环境变量

复制示例配置文件并按需修改：

```bash
cp .env.example .env
```

`.env` 文件内容说明：

```ini
# 数据库连接地址（SQLite）
DATABASE_URL=sqlite+aiosqlite:///./data/novel_agent.db

# 服务端主密钥（用于 API 密钥加密，生产环境务必修改）
SECRET_KEY=change-me-in-production

# 调试模式
DEBUG=True

# CORS 允许的前端源地址
CORS_ORIGINS=["http://localhost:5173"]
```

> **注意**：开发环境可使用相对路径；生产环境请使用独立数据库并替换 `SECRET_KEY`。

### 3.3 启动后端服务

```bash
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动成功后会看到：

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 3.4 验证后端

- API 文档：浏览器打开 http://localhost:8000/docs
- 健康检查：访问 http://localhost:8000/api/v1/projects 应返回 `{"data":[],"total":0,"page":1,"page_size":20}`

---

## 4. 前端启动

### 4.1 安装依赖

```bash
cd frontend
npm install
```

### 4.2 启动开发服务器

```bash
cd frontend
npm run dev
```

启动成功后会看到：

```
VITE v8.x.x  ready in xxx ms

➜  Local:   http://localhost:5173/
```

### 4.3 访问应用

浏览器打开 http://localhost:5173

> 前端开发服务器已配置代理，所有 `/api` 请求自动转发到后端 `http://localhost:8000`。

进入任意项目后，左侧项目导航应显示「有声书」。如果 5173 端口已被旧前端占用，请先在旧终端按 `Ctrl+C` 停止它，再重新执行本目录下的 `npm run dev`，并在浏览器中强制刷新。

---

## 5. 生产构建

### 5.1 前端构建

```bash
cd frontend
npm run build
```

构建产物输出到 `frontend/dist/` 目录。

### 5.2 后端生产启动

```bash
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

> 有声书后台任务使用进程内执行器。启用有声书生成时请设置 `--workers 1`；未完成任务会在服务重启后从头恢复。

---

## 6. 运行测试

### 6.1 后端单元测试

```bash
cd backend
pip install pytest pytest-asyncio
python -m pytest tests/ -v
```

### 6.2 前端类型检查

```bash
cd frontend
npx tsc --noEmit
```

---

## 7. 使用流程

### 第一步：配置 LLM

1. 打开应用，点击左侧导航「设置」
2. 点击「添加配置」
3. 填写 LLM 服务商信息：
   - 服务商：`deepseek` / `openai` / `anthropic` / `google` / `openai_compatible`
   - API 密钥：你的 LLM API Key
   - Base URL：API 地址（如 `https://api.deepseek.com`、`https://api.openai.com/v1`）
   - 模型名称：如 `deepseek-v4-pro`、`gpt-5.5`、`claude-sonnet-4-6`、`gemini-3.5-flash`
4. 点击「创建」
5. 点击「测试连接」验证配置是否正确

不同服务商的推荐模型和消息格式见 [LLM Provider 支持](docs/llm-providers.md)。

### 第二步：创建项目

1. 在首页点击「新建项目」
2. 填写项目名称、体裁、描述，可选择小说封面
3. 点击「创建」
4. 在项目卡片中可继续添加、更换或删除封面

### 第三步：构建大纲

1. 选择项目后，点击左侧导航「大纲」
2. 点击「AI 生成大纲」，填写体裁、主题、风格等参数
3. 生成后可手动添加/编辑/删除节点
4. 选中节点后点击 ✨ 按钮可 AI 扩展子节点

### 第四步：定义人物

1. 点击左侧导航「人物」
2. 点击「添加人物」手动创建
3. 切换到「关系图谱」查看人物关系网络

### 第五步：整理场景

1. 点击左侧导航「场景」
2. 添加小说中经常出现的地点、氛围、关键细节和备注
3. 在「小说内容」的 AI 输入面板中按需勾选场景，只有选中的场景会加入本章 AI 编写输入

### 第六步：章节创作

1. 创建章节后进入编辑器
2. 使用 TipTap 富文本编辑器撰写内容
3. 点击右侧「AI 助手」面板，选择操作类型：
   - **续写**：AI 根据前文自动续写
   - **改写**：选中文本后 AI 改写
   - **润色**：选中文本后 AI 润色
   - **扩写**：选中文本后 AI 扩展
   - **摘要**：AI 生成章节摘要
   - **对话**：AI 根据人物信息生成对话
4. 使用「AI 打磨」时可选择加入前一章节或后一章节与摘要作为输入上下文
5. 编辑器支持自动保存（3秒防抖）

### 第七步：一致性检查

1. 点击左侧导航「一致性」
2. 查看历史分析报告
3. 报告包含问题列表和修改建议

### 第八步：生成有声书

1. 点击左侧导航「有声书」；可选择现有 LLM，粘贴语音 API 文档并自动生成接入设置
2. 也可手动选择 MiniMax 异步多角色、OpenAI 兼容/vLLM、通用 HTTP/WebSocket API 或 ComfyUI 工作流
3. 单独粘贴语音 API Key 并保存 TTS 配置；设置各人物音色后，点击「人物声音保存」单独保存映射
4. 选择语音脚本 LLM 以及全书、卷或章节范围，一键生成合并 MP3 与单章 MP3

MiniMax 异步多角色模式会为每个连续同音色片段创建独立任务。系统设置中的 FFmpeg 高质量拼接默认开启，用于统一响度、插入切换停顿并按序编码；也可关闭该选项，改为直接生成并自动拼接多个 MP3，此时无需安装 FFmpeg。

每章在调用 TTS 前会先交给所选 LLM，生成经过人物 ID、内容覆盖度和结构校验的语音脚本 JSON；后端再补全旁白/人物 `voice_id` 并构造语音模型请求。语音脚本随任务持久化，任务恢复时不会无故重复调用 LLM。

使用 DeepSeek V4 生成语音脚本时，请求会按官方当前最大输出长度将 `max_tokens` 提高到 384K，避免项目 LLM 配置中的较小默认值导致 `finish_reason=length`。

MiniMax 音色库通过官方接口查询和删除音色，删除后会立即重新拉取远端列表。刚设计但尚未正式调用的音色会保留本地记录，刷新页面后仍可管理；对于查询不到但 ID 已占用的历史音色，也可按 `voice_id` 手工删除。MiniMax 不允许再次使用已删除的 `voice_id`，系统会记录这类 ID 并在创建前提示换用新 ID。

具体服务协议、ComfyUI 占位符和对白识别规则见 [`docs/audiobook.md`](docs/audiobook.md)。

### 第九步：导出

1. 点击左侧导航「导出」
2. 选择导出格式（Markdown / TXT / DOCX）
3. 勾选是否包含大纲和人物档案
4. 点击「导出」下载文件
5. 点击「一键导出到番茄」或「一键导出到起点」可复制平台投稿文本并打开作者后台

---

## 8. API 接口速查

> 所有业务资源（大纲、人物、场景、章节、分析、导出）的 API 都嵌套在项目路径 `/api/v1/projects/{project_id}/...` 下。LLM 配置是全局资源，路径独立。详细 schema 启动后端后访问 `/docs`。

| 模块 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 项目 | GET | `/api/v1/projects` | 获取项目列表（分页） |
| 项目 | POST | `/api/v1/projects` | 创建项目 |
| 项目 | GET | `/api/v1/projects/{id}` | 获取项目详情 |
| 项目 | PUT | `/api/v1/projects/{id}` | 更新项目 |
| 项目 | PUT | `/api/v1/projects/{id}/cover` | 上传或更换项目封面 |
| 项目 | DELETE | `/api/v1/projects/{id}/cover` | 删除项目封面 |
| 项目 | DELETE | `/api/v1/projects/{id}` | 删除项目（级联） |
| 大纲 | GET | `/api/v1/projects/{pid}/outlines` | 获取项目大纲列表 |
| 大纲 | POST | `/api/v1/projects/{pid}/outlines` | 创建大纲 |
| 大纲 | POST | `/api/v1/projects/{pid}/outlines/generate` | AI 生成大纲 |
| 大纲 | GET | `/api/v1/projects/{pid}/outlines/{id}/tree` | 获取大纲树 |
| 大纲 | POST | `/api/v1/projects/{pid}/outlines/nodes/{id}/expand` | AI 扩展节点 |
| 大纲 | POST | `/api/v1/projects/{pid}/outlines/{id}/optimize` | AI 优化大纲 |
| 人物 | GET | `/api/v1/projects/{pid}/characters` | 获取人物列表 |
| 人物 | POST | `/api/v1/projects/{pid}/characters` | 创建人物 |
| 人物 | PUT | `/api/v1/projects/{pid}/characters/{id}` | 更新人物 |
| 人物 | DELETE | `/api/v1/projects/{pid}/characters/{id}` | 删除人物 |
| 人物 | POST | `/api/v1/projects/{pid}/characters/generate` | AI 单个生成 |
| 人物 | POST | `/api/v1/projects/{pid}/characters/import` | AI 一键导入多人物（从文本） |
| 人物 | GET | `/api/v1/projects/{pid}/characters/relationships` | 获取关系列表 |
| 人物 | POST | `/api/v1/projects/{pid}/characters/relationships` | 创建关系 |
| 场景 | GET | `/api/v1/projects/{pid}/scenes` | 获取场景列表 |
| 场景 | POST | `/api/v1/projects/{pid}/scenes` | 创建场景 |
| 场景 | POST | `/api/v1/projects/{pid}/scenes/import` | AI 导入一个或多个场景 |
| 场景 | PUT | `/api/v1/projects/{pid}/scenes/{id}` | 更新场景 |
| 场景 | DELETE | `/api/v1/projects/{pid}/scenes/{id}` | 删除场景 |
| 章节 | GET | `/api/v1/projects/{pid}/chapters` | 获取章节列表 |
| 章节 | POST | `/api/v1/projects/{pid}/chapters` | 创建章节 |
| 章节 | POST | `/api/v1/projects/{pid}/chapters/{id}/ai-assist` | AI 辅助（续写/改写/润色等） |
| 章节 | POST | `/api/v1/projects/{pid}/chapters/{id}/ai-stream` | AI 流式辅助（SSE） |
| 章节 | POST | `/api/v1/projects/{pid}/chapters/{id}/novel-write` | 一键整本写（同步） |
| 章节 | POST | `/api/v1/projects/{pid}/chapters/{id}/novel-write-stream` | 一键整本写（流式 SSE） |
| 章节 | POST | `/api/v1/projects/{pid}/chapters/{id}/novel-polish` | AI 打磨章节（可带前/后章上下文） |
| 章节 | POST | `/api/v1/projects/{pid}/chapters/{id}/novel-polish-stream` | AI 流式打磨章节（SSE） |
| Agent | POST | `/api/v1/projects/{pid}/novel-agent/write` | 从想法生成项目蓝图、人物、场景、章节并自动写作正文 |
| Agent | POST | `/api/v1/projects/{pid}/novel-agent/write-stream` | 生成 Agent 蓝图并等待用户确认，不修改项目内容 |
| Agent | POST | `/api/v1/projects/{pid}/novel-agent/write-execute-stream` | 用户确认后执行 Agent 蓝图 |
| Agent | POST | `/api/v1/projects/{pid}/novel-agent/continue-stream` | 生成续写改编 Plan 并等待用户确认，不修改章节 |
| Agent | POST | `/api/v1/projects/{pid}/novel-agent/continue-execute-stream` | 用户确认后执行续写与打磨 Plan |
| Agent | GET / POST | `/api/v1/projects/{pid}/novel-agent/sessions` | 查询或新建 Agent Session |
| Agent | GET / PUT / DELETE | `/api/v1/projects/{pid}/novel-agent/sessions/{sid}` | 读取、重命名或删除 Agent Session |
| 章节 | GET | `/api/v1/projects/{pid}/chapters/{id}/versions` | 获取版本列表 |
| 章节 | POST | `/api/v1/projects/{pid}/chapters/{id}/versions` | 创建版本快照 |
| 章节 | GET | `/api/v1/projects/{pid}/chapters/{id}/versions/compare?v1=&v2=` | 版本对比 |
| 分析 | POST | `/api/v1/projects/{pid}/analysis/consistency` | 一致性分析 |
| 分析 | POST | `/api/v1/projects/{pid}/analysis/consistency/stream` | 流式一致性分析（SSE） |
| 分析 | GET | `/api/v1/projects/{pid}/analysis/reports` | 分析报告列表 |
| 导出 | POST | `/api/v1/projects/{pid}/export` | 导出项目（TXT/Markdown/DOCX） |
| 导出 | POST | `/api/v1/projects/{pid}/export/platform` | 生成番茄/起点平台导出包 |
| 有声书 | GET / PUT | `/api/v1/projects/{pid}/audiobook/config` | 读取或保存 TTS/声音配置 |
| 有声书 | PATCH | `/api/v1/projects/{pid}/audiobook/config/character-voices` | 单独保存人物音色映射 |
| 有声书 | POST | `/api/v1/projects/{pid}/audiobook/config/parse-docs` | 使用现有 LLM 自动解析语音 API 文档 |
| 有声书 | POST | `/api/v1/projects/{pid}/audiobook/preview` | 生成声音试听 |
| 有声书 | POST | `/api/v1/projects/{pid}/audiobook/voices/query` | 查询 MiniMax 可用音色 |
| 有声书 | POST | `/api/v1/projects/{pid}/audiobook/voices/design` | 设计 MiniMax 音色并生成试听 |
| 有声书 | POST | `/api/v1/projects/{pid}/audiobook/voices/delete` | 删除 MiniMax 复刻或设计音色 |
| 有声书 | GET | `/api/v1/projects/{pid}/audiobook/scopes` | 获取全书、卷、章节范围 |
| 有声书 | GET / POST | `/api/v1/projects/{pid}/audiobook/jobs` | 查询或创建生成任务（创建时需指定语音脚本 `llm_config_id`） |
| 有声书 | GET | `/api/v1/projects/{pid}/audiobook/jobs/{id}/files/{filename}` | 下载 MP3 |
| 配置 | GET | `/api/v1/llm-configs` | 获取 LLM 配置列表 |
| 配置 | POST | `/api/v1/llm-configs` | 创建 LLM 配置 |
| 配置 | PUT | `/api/v1/llm-configs/{id}` | 更新 LLM 配置 |
| 配置 | DELETE | `/api/v1/llm-configs/{id}` | 删除 LLM 配置 |
| 配置 | POST | `/api/v1/llm-configs/{id}/test` | 测试连接 |

完整接口文档请参考 `docs/api.md`，或启动后端后访问 http://localhost:8000/docs 查看交互式 API 文档。

---

## 9. 常见问题

### Q: 后端启动报 `unable to open database file`

**A**: 检查 `.env` 中 `DATABASE_URL` 路径是否正确，确保使用绝对路径且 `data/` 目录已创建：

```bash
mkdir -p data
```

### Q: 前端请求 API 报 404

**A**: 确保后端服务已启动（端口 8000），前端开发服务器的代理配置在 `vite.config.ts` 中：

```typescript
server: {
  proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } }
}
```

### Q: AI 功能无法使用

**A**: 需要先在「设置」页面配置有效的 LLM API 密钥，并确保网络可以访问对应的 LLM 服务。

### Q: 导出 DOCX 格式报错

**A**: DOCX 导出依赖 `python-docx` 库，需额外安装：

```bash
pip install python-docx
```

### Q: 如何重置数据库

**A**: 删除 `data/novel_agent.db` 文件，重启后端服务即可自动重建：

```bash
rm data/novel_agent.db
```

### Q: 改了 `SECRET_KEY` 之后所有 LLM 调用都报解密失败

**A**: 这是设计缺陷——`SECRET_KEY` 是 LLM API 密钥加密的根密钥，**改了之后旧数据全部解不开**。处理方式：

1. 在「设置」里把每个 LLM 配置的 API key 重新填一次
2. 或者回滚 `SECRET_KEY` 到旧值

**生产环境务必先用 32 字节随机密钥配好 `SECRET_KEY`，备份 `.env` 文件**。详见 `docs/deployment.md` 第 1.1 节和 `docs/troubleshooting.md` 第 6 条。

### Q: LLM 调通，但前端 catch 块统一报错误导

**A**: 当前 `frontend/src/modules/character/CharacterManager.tsx` 等多个模块的 catch 块对所有错误吐同一句"导入失败，请检查 LLM 配置后重试"，调试时建议在 catch 里 `console.error(error.response?.data?.detail || error.message)` 看后端实际报错。已知案例：因 `LLMConfig.default_params=None` 触发的 `TypeError` 长期被这句话掩盖，已在 `docs/troubleshooting.md` 第 1 条记录。

---

## 10. 延伸阅读

| 文档 | 用途 |
|------|------|
| `docs/architecture.md` | 系统架构、模块关系、数据流、部署拓扑 |
| `docs/api.md` | 完整 REST API 端点 + 请求/响应 schema |
| `docs/implementation.md` | 各模块实现细节、关键代码片段 |
| `docs/development.md` | 开发指南：新增 LLM Provider / API / 前端页面 |
| `docs/deployment.md` | 部署文档：环境变量、生产配置、安全清单 |
| `docs/data-model.md` | 数据模型：ER 图、表字段、级联规则、索引 |
| `docs/troubleshooting.md` | 常见问题与已知 bug 复盘 |
| `docs/audiobook.md` | 有声书服务接入、ComfyUI 工作流和任务说明 |
| `docs/novel-agent.md` | Agent 生成、续写改编、Session 持久化和扩展说明 |
