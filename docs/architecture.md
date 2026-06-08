# Novel Writing Agent — 架构设计文档

## 1. 系统概述

### 1.1 项目定位

Novel Writing Agent 是一款面向小说创作者的智能辅助应用，通过集成远程 LLM API（如 DeepSeek V4 Pro），为用户提供从大纲构建、人物设定到章节创作的全流程辅助能力。系统核心价值在于利用大语言模型的推理与生成能力，帮助作者维持小说内容的整体性与情节连贯性。

### 1.2 核心目标

| 目标 | 描述 |
|------|------|
| 全流程覆盖 | 支持大纲设计 → 人物设定 → 章节创作的完整创作链路 |
| 智能辅助 | 通过 LLM 实现大纲自动生成、一致性检测、内容优化建议 |
| 数据安全 | API 密钥加密存储、用户数据本地持久化 + 可选云端同步 |
| 流畅体验 | 响应式前端设计、LLM 流式输出、请求频率智能控制 |

### 1.3 核心设计原则：项目为中心

**写作项目（Project）是系统的核心组织单元**，所有创作资源（大纲、人物、章节、一致性分析报告）均从属于某个写作项目，不存在脱离项目的独立资源。这一原则体现在：

- **数据层面**：所有业务实体通过 `project_id` 外键关联到 Project，级联删除保证数据完整性
- **API 层面**：所有业务接口以 `/projects/{project_id}/...` 为路径前缀，形成 RESTful 嵌套资源
- **前端层面**：用户先选择/创建项目，再在项目上下文中操作大纲、人物、章节等功能

```
Project（写作项目）
├── Outline（大纲）── OutlineNode（大纲节点，树形结构）
├── Character（人物）── CharacterRelationship（人物关系）
├── Chapter（章节）── ChapterVersion（章节版本）
└── AnalysisReport（一致性分析报告）
```

---

## 2. 系统架构总览

### 2.1 架构风格

采用 **前后端分离** 的 B/S 架构，前端为 SPA（单页应用），后端为 RESTful API 服务。整体遵循分层架构与模块化设计原则。

```
┌─────────────────────────────────────────────────────────┐
│                    客户端层 (Client)                      │
│  ┌──────────────────────────────────────────────────┐   │
│  │              项目工作区 (Project Workspace)        │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐         │   │
│  │  │ 大纲编辑  │ │ 人物管理  │ │ 章节编辑器 │         │   │
│  │  └────┬─────┘ └────┬─────┘ └─────┬─────┘         │   │
│  │       └─────────────┴──────────────┘              │   │
│  │                    │                              │   │
│  │           ┌────────┴────────┐                     │   │
│  │           │  一致性分析报告   │                     │   │
│  │           └─────────────────┘                     │   │
│  └──────────────────────────────────────────────────┘   │
│                         │                                │
│              ┌──────────┴──────────┐                     │
│              │   前端状态管理 Store  │                     │
│              └──────────┬──────────┘                     │
│                         │ HTTP / SSE                     │
└─────────────────────────┼───────────────────────────────┘
                          │
┌─────────────────────────┼───────────────────────────────┐
│                    服务端层 (Server)                       │
│              ┌──────────┴──────────┐                     │
│              │     API Gateway     │                     │
│              └──────────┬──────────┘                     │
│       ┌────────────────┼────────────────┐                │
│  ┌────┴─────┐   ┌──────┴──────┐   ┌────┴──────┐        │
│  │ 项目服务  │   │  LLM 服务    │   │ 分析服务   │        │
│  └────┬─────┘   └──────┬──────┘   └─────┬─────┘        │
│       │                │                 │               │
│  ┌────┴────────────────┴─────────────────┴─────┐        │
│  │              数据访问层 (DAL)                 │        │
│  └──────────────────┬──────────────────────────┘        │
│                     │                                    │
└─────────────────────┼────────────────────────────────────┘
                      │
┌─────────────────────┼────────────────────────────────────┐
│                  数据层 (Data)                             │
│       ┌─────────────┴──────────────┐                     │
│       │                            │                     │
│  ┌────┴─────┐              ┌───────┴───────┐             │
│  │ SQLite   │              │  远程 LLM API  │             │
│  │ (本地)    │              │ (DeepSeek等)   │             │
│  └──────────┘              └───────────────┘             │
└──────────────────────────────────────────────────────────┘
```

### 2.2 架构分层说明

| 层次 | 职责 | 关键技术 |
|------|------|----------|
| 客户端层 | UI 渲染、用户交互、本地缓存、状态管理 | React 19 + TypeScript, Zustand, TailwindCSS |
| 服务端层 | 业务逻辑、LLM 调用编排、一致性分析、数据持久化 | Python 3.11+, FastAPI, SQLAlchemy |
| 数据层 | 数据存储、外部 API 对接 | SQLite(本地), 远程 LLM REST API |

---

## 3. 技术选型

### 3.1 前端技术栈

| 技术 | 版本 | 选型理由 |
|------|------|----------|
| React | 19.x | 组件化生态成熟，社区资源丰富，适合复杂交互界面 |
| TypeScript | 6.x | 静态类型保障，提升大型项目可维护性 |
| Vite | 8.x | 极速 HMR，构建性能优异 |
| Zustand | 5.x | 轻量状态管理，API 简洁，无样板代码 |
| TailwindCSS | 4.x | 原子化 CSS，响应式设计友好 |
| @xyflow/react | 12.x | 人物关系图谱可视化 |
| TipTap | 3.x | 富文本编辑器，支持扩展、批注、协作 |
| React Router | 7.x | SPA 路由管理，支持嵌套路由 |
| Axios | 1.x | HTTP 客户端，拦截器机制完善 |
| lucide-react | 1.x | 图标库 |
| diff-match-patch | 1.x | 版本差异对比 |

### 3.2 后端技术栈

| 技术 | 版本 | 选型理由 |
|------|------|----------|
| Python | 3.11+ | AI/ML 生态丰富，开发效率高 |
| FastAPI | 0.110+ | 异步高性能，自动 OpenAPI 文档生成 |
| SQLAlchemy | 2.x | ORM 成熟，支持异步，多数据库切换 |
| SQLite | - | 零配置本地存储，单用户场景足够 |
| httpx | 0.27+ | 异步 HTTP 客户端，用于调用 LLM API |
| Pydantic | 2.x | 数据校验与序列化，与 FastAPI 深度集成 |
| cryptography | 42.x | API 密钥加密存储 |

### 3.3 开发与部署工具

| 工具 | 用途 |
|------|------|
| Docker + Docker Compose | 容器化部署 |
| GitHub Actions | CI/CD |
| ESLint + Prettier | 前端代码规范 |
| Ruff + Black | 后端代码规范 |
| pytest + Vitest | 测试框架 |

---

## 4. 模块设计

### 4.1 模块依赖关系

```
┌─────────────────────────────────────────────────────┐
│                   前端模块                            │
│                                                     │
│  ┌─────────────────────────────────────────────┐    │
│  │        项目工作区 (Project Workspace)         │    │
│  │                                             │    │
│  │  ┌─────────┐  ┌─────────┐  ┌──────────┐   │    │
│  │  │ 大纲构建 │  │ 人物定义 │  │ 章节编辑  │   │    │
│  │  │ Module  │  │ Module  │  │  Module  │   │    │
│  │  └────┬────┘  └────┬────┘  └─────┬────┘   │    │
│  │       └─────────────┼─────────────┘        │    │
│  │                     │                       │    │
│  │       ┌─────────────┼─────────────┐        │    │
│  │       │             │             │        │    │
│  │  ┌────┴─────┐ ┌────┴──────┐ ┌───┴──────┐ │    │
│  │  │ 一致性检测 │ │ LLM 配置  │ │ 导出/同步 │ │    │
│  │  │ Module   │ │ Module    │ │ Module   │ │    │
│  │  └──────────┘ └───────────┘ └──────────┘ │    │
│  └─────────────────────────────────────────────┘    │
│                                                     │
│  ┌──────────────┐                                   │
│  │ 项目管理 Module│ ← 独立于工作区，管理项目列表       │
│  └──────────────┘                                   │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│                   后端模块                            │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │          项目服务 (Project Service)            │   │
│  │  ┌──────────┐  ┌──────────┐  ┌────────────┐ │   │
│  │  │ 大纲服务  │  │ 人物服务  │  │  章节服务   │ │   │
│  │  │ Outline  │  │ Character│  │  Chapter   │ │   │
│  │  │ Service  │  │ Service  │  │  Service   │ │   │
│  │  └────┬─────┘  └────┬─────┘  └─────┬──────┘ │   │
│  │       └──────────────┼──────────────┘        │   │
│  │                      │                        │   │
│  │       ┌──────────────┴──────────────┐        │   │
│  │       │     一致性分析 Consistency    │        │   │
│  │       │       Service               │        │   │
│  │       └─────────────────────────────┘        │   │
│  └──────────────────────────────────────────────┘   │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │          LLM 编排服务 LLM Orchestrator         │   │
│  └──────────────────────┬───────────────────────┘   │
│                         │                           │
│  ┌──────────┐    ┌──────┴───────┐  ┌────────────┐  │
│  │ 导出服务  │    │  API 配置    │  │             │  │
│  │ Export   │    │  Config Svc  │  │             │  │
│  │ Service  │    │              │  │             │  │
│  └──────────┘    └──────────────┘  └────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 4.2 项目管理模块

**职责**：管理写作项目的创建、编辑、删除，作为所有创作资源的顶层容器。

**核心数据模型**：

```
Project
├── id: UUID
├── name: string (200)
├── description: text
├── genre: string (100)
├── status: enum [draft, in_progress, completed]
├── word_count_target: integer
├── settings: text (JSON)
├── created_at: datetime
├── updated_at: datetime
├── outlines: Outline[]          ← 项目包含大纲
├── characters: Character[]      ← 项目包含人物
├── chapters: Chapter[]          ← 项目包含章节
└── analysis_reports: AnalysisReport[]  ← 项目包含分析报告
```

**项目与子资源的关系**：

| 子资源 | 关系类型 | 级联行为 |
|--------|----------|----------|
| Outline | 1:N | 删除项目时级联删除所有大纲 |
| Character | 1:N | 删除项目时级联删除所有人物 |
| Chapter | 1:N | 删除项目时级联删除所有章节 |
| AnalysisReport | 1:N | 删除项目时级联删除所有分析报告 |

### 4.3 小说大纲构建模块

**职责**：管理小说的结构化大纲，支持多级章节划分、情节节点设置、关键事件标记，以及基于 LLM 的大纲自动生成与优化。大纲从属于写作项目。

**核心数据模型**：

```
Outline
├── id: UUID
├── project_id: UUID (FK → Project)
├── title: string
├── description: text
├── version: integer
├── created_at: datetime
├── updated_at: datetime
└── nodes: OutlineNode[]

OutlineNode
├── id: UUID
├── outline_id: UUID (FK → Outline)
├── parent_id: UUID? (FK → OutlineNode, 自引用)
├── node_type: enum [VOLUME, CHAPTER, SCENE, PLOT_POINT, KEY_EVENT]
├── title: string
├── summary: text
├── sort_order: integer
├── metadata: JSON
│   ├── plot_keywords: string[]
│   ├── emotional_tone: string
│   ├── time_setting: string
│   └── location: string
├── llm_generated: boolean
└── children: OutlineNode[]
```

**LLM 交互策略**：

| 场景 | Prompt 策略 | 模型参数 |
|------|-------------|----------|
| 从零生成大纲 | System: 资深小说策划; User: 体裁+主题+风格描述 | temperature=1.1, 不传 top_k |
| 扩展子节点 | System: 大纲扩展专家; User: 父节点内容+扩展要求 | temperature=1.1, 不传 top_k |
| 优化大纲结构 | System: 叙事结构顾问; User: 完整大纲+优化方向 | temperature=1.1, 不传 top_k |
| 生成情节节点 | System: 情节设计专家; User: 上下文+情节需求 | temperature=1.3, 不传 top_k |

### 4.4 小说人物定义模块

**职责**：管理人物档案信息，维护人物关系网络，提供关系图谱可视化。人物从属于写作项目。

**核心数据模型**：

```
Character
├── id: UUID
├── project_id: UUID (FK → Project)
├── name: string
├── aliases: string[]
├── avatar_url: string?
├── basic_info: JSON
│   ├── age: string
│   ├── gender: string
│   ├── occupation: string
│   ├── appearance: text
│   └── background: text
├── personality: JSON
│   ├── traits: string[]
│   ├── mbti: string?
│   ├── values: string[]
│   ├── flaws: string[]
│   └── speaking_style: text
├── growth_arc: JSON
│   ├── starting_state: text
│   ├── catalyst: text
│   ├── transformation: text
│   └── ending_state: text
├── notes: text
├── created_at: datetime
└── updated_at: datetime

CharacterRelationship
├── id: UUID
├── project_id: UUID (FK → Project)
├── source_id: UUID (FK → Character)
├── target_id: UUID (FK → Character)
├── relationship_type: enum
│   [FAMILY, FRIEND, ENEMY, LOVER, MENTOR, SUBORDINATE, ALLY, RIVAL, OTHER]
├── description: text
├── intensity: integer (1-10)
├── start_chapter: string?
├── end_chapter: string?
└── metadata: JSON
```

**关系图谱可视化**：使用 React Flow 构建有向图，节点为人物卡片，边为关系连线，支持：
- 拖拽布局
- 关系类型颜色编码
- 节点点击展开详情
- 按关系类型筛选
- 动态增删节点/边

### 4.5 整体性与连贯性保障模块

**职责**：实时检测章节间的逻辑一致性、人物行为连贯性、情节发展合理性，提供修改建议。一致性分析报告从属于写作项目。

**检测维度**：

| 维度 | 检测内容 | 触发时机 |
|------|----------|----------|
| 人物一致性 | 性格行为是否与设定矛盾、称呼是否统一 | 章节保存时 |
| 时间线一致性 | 事件时间顺序是否合理、时间跨度是否矛盾 | 章节保存时 |
| 情节连贯性 | 前后章节情节是否衔接、伏笔是否回收 | 手动触发 / 章节完成时 |
| 设定一致性 | 世界观设定是否前后矛盾 | 手动触发 / 章节完成时 |
| 逻辑合理性 | 因果关系是否成立、动机是否充分 | 手动触发 |

**分析引擎架构**：

```
┌──────────────────────────────────────────────┐
│            Consistency Analyzer               │
│                                              │
│  ┌────────────┐      ┌──────────────────┐   │
│  │ Context    │      │  Analysis        │   │
│  │ Assembler  │─────→│  Pipeline        │   │
│  │            │      │                  │   │
│  │ - 人物设定  │      │  ┌────────────┐  │   │
│  │ - 大纲结构  │      │  │ Rule-based │  │   │
│  │ - 前文摘要  │      │  │ Checker    │  │   │
│  │ - 当前章节  │      │  └─────┬──────┘  │   │
│  └────────────┘      │        │         │   │
│                      │  ┌─────┴──────┐  │   │
│                      │  │ LLM-based  │  │   │
│                      │  │ Analyzer   │  │   │
│                      │  └─────┬──────┘  │   │
│                      │        │         │   │
│                      │  ┌─────┴──────┐  │   │
│                      │  │ Suggestion │  │   │
│                      │  │ Generator  │  │   │
│                      │  └────────────┘  │   │
│                      └──────────────────┘   │
└──────────────────────────────────────────────┘
```

**规则检测（Rule-based Checker）**：
- 人物名称拼写检查（与人物库比对）
- 时间标记提取与冲突检测（正则 + 时间线排序）
- 设定关键词冲突检测（基于设定词典）
- 章节字数/结构异常检测

**LLM 深度分析（LLM-based Analyzer）**：
- 将上下文组装为结构化 Prompt
- 分维度请求 LLM 分析
- 流式返回分析结果与建议

### 4.6 LLM API 集成模块

**职责**：管理 LLM API 配置、请求调度、响应处理、错误重试。LLM 配置为全局资源，不绑定特定项目。

**配置模型**（`backend/app/models/llm_config.py`）：

```
LLMConfig
├── id: UUID
├── provider: string (deepseek | openai | anthropic | google | openai_compatible)
├── api_key_encrypted: string (AES-256-GCM 加密，base64 密文)
├── base_url: string
├── model_name: string
├── default_params: dict (JSON)
│   ├── temperature: float (0.0-2.0)
│   ├── top_p: float (0.0-1.0)
│   ├── max_tokens: integer
│   ├── frequency_penalty: float
│   └── presence_penalty: float
├── rate_limit: dict (JSON, 可选)
│   ├── requests_per_minute: integer
│   ├── tokens_per_minute: integer
│   └── max_concurrent: integer
├── is_active: boolean
├── created_at: datetime
└── updated_at: datetime
```

> 字段详细说明、JSON 结构、级联规则见 `docs/data-model.md` 第 3.9 节。

**请求调度机制**：

```
┌─────────────────────────────────────────────┐
│            LLM Orchestrator                  │
│                                             │
│  ┌─────────────┐     ┌──────────────────┐  │
│  │ Request     │     │  Rate Limiter     │  │
│  │ Queue       │────→│  (Token Bucket)   │  │
│  └─────────────┘     └────────┬─────────┘  │
│                               │             │
│                      ┌────────┴─────────┐  │
│                      │  Request Builder  │  │
│                      │  - Prompt模板     │  │
│                      │  - 上下文组装     │  │
│                      │  - 参数注入       │  │
│                      └────────┬─────────┘  │
│                               │             │
│                      ┌────────┴─────────┐  │
│                      │  HTTP Client      │  │
│                      │  (httpx async)    │  │
│                      │  - 流式响应       │  │
│                      │  - 超时控制       │  │
│                      │  - 重试机制       │  │
│                      └────────┬─────────┘  │
│                               │             │
│                      ┌────────┴─────────┐  │
│                      │  Response Parser  │  │
│                      │  - SSE 解析       │  │
│                      │  - 内容提取       │  │
│                      │  - 用量统计       │  │
│                      └──────────────────┘  │
└─────────────────────────────────────────────┘
```

**安全设计**：
- API 密钥使用 AES-256-GCM 加密存储，密钥派生自服务器主密钥
- 前端不直接持有 API 密钥明文，所有 LLM 请求经后端代理转发
- 请求日志脱敏处理，不记录完整 Prompt/Response 内容
- 支持 API 密钥轮换，无需重启服务

### 4.7 前端交互界面模块

**页面结构**：

```
App
├── / (项目列表页)
│   └── ProjectList
├── /projects/:projectId (项目工作区，嵌套布局)
│   ├── Layout (项目工作区布局)
│   │   ├── Sidebar (项目内导航)
│   │   │   ├── 项目概览
│   │   │   ├── 大纲视图
│   │   │   ├── 人物管理
│   │   │   ├── 章节列表
│   │   │   ├── 一致性报告
│   │   │   └── 导出
│   │   └── Main Content Area
│   ├── /projects/:projectId/outline
│   │   └── OutlineEditor
│   ├── /projects/:projectId/characters
│   │   ├── CharacterManager
│   │   │   ├── CharacterList
│   │   │   ├── CharacterDetail
│   │   │   └── RelationshipGraph
│   ├── /projects/:projectId/chapters/:chapterId
│   │   └── ChapterEditor
│   │       ├── TipTap Editor
│   │       ├── AI Assist Panel
│   │       └── Version History
│   ├── /projects/:projectId/consistency
│   │   └── ConsistencyReport
│   └── /projects/:projectId/export
│       └── ExportPanel
├── /settings (全局设置)
│   └── LLMConfigPanel
└── Modals / Dialogs
    ├── NewProjectDialog
    ├── LLMConfigDialog
    ├── ExportDialog
    └── VersionCompareDialog
```

**编辑器功能**：

| 功能 | 实现方式 |
|------|----------|
| 富文本编辑 | TipTap Editor + 自定义扩展 |
| AI 辅助面板 | 侧边栏，支持续写/改写/润色/对话 |
| 批注系统 | TipTap Annotation 扩展 |
| 版本对比 | diff-match-patch 算法，双栏对比视图 |
| 自动保存 | 防抖 3s 自动保存 + 手动 Ctrl+S |
| 导出 | 支持 TXT / Markdown / DOCX |

---

## 5. 数据流设计

### 5.1 大纲生成数据流

```
用户在项目工作区内输入创作描述
       │
       ▼
前端 OutlineEditor ──POST /api/v1/projects/{pid}/outlines/generate──→ 后端 OutlineService
                                                      │
                                                      ▼
                                               LLM Orchestrator
                                                      │
                                              ┌───────┴───────┐
                                              │ Prompt 构建    │
                                              │ - System Prompt│
                                              │ - 用户描述     │
                                              │ - 输出格式约束 │
                                              └───────┬───────┘
                                                      │
                                                      ▼
                                              远程 LLM API
                                              (流式 SSE 响应)
                                                      │
                                              ┌───────┴───────┐
                                              │ 响应解析       │
                                              │ - 结构化提取   │
                                              │ - 节点树构建   │
                                              └───────┬───────┘
                                                      │
                                                      ▼
                                               保存至 SQLite
                                                      │
                                                      ▼
前端接收 SSE 流 ←──SSE 推送──────────────────── 后端返回结果
       │
       ▼
大纲树形视图实时渲染
```

### 5.2 一致性检测数据流

```
用户在项目工作区内触发检测 (保存章节 / 手动触发)
       │
       ▼
前端 ──POST /api/v1/projects/{pid}/analysis/consistency──→ 后端 ConsistencyService
                                            │
                                            ▼
                                     Context Assembler
                                     ┌──────────────────┐
                                     │ 1. 加载项目人物设定│
                                     │ 2. 加载项目大纲结构│
                                     │ 3. 提取前文摘要    │
                                     │ 4. 获取当前章节    │
                                     └────────┬─────────┘
                                              │
                                              ▼
                                     Rule-based Checker
                                     (快速规则过滤)
                                              │
                                     ┌────────┴────────┐
                                     │ LLM Deep Analysis│
                                     │ (分维度并行请求)  │
                                     └────────┬────────┘
                                              │
                                              ▼
                                     Suggestion Generator
                                     (整合结果 + 生成建议)
                                              │
                                              ▼
                                     保存分析报告 → SQLite
                                              │
                                              ▼
前端展示一致性报告 ←────── 返回分析结果 ──────┘
```

---

## 6. 部署架构

### 6.1 开发环境

```
开发者机器
├── 前端 Dev Server (Vite, port 5173)
├── 后端 API Server (Uvicorn, port 8000)
└── SQLite 数据库文件 (./data/novel_agent.db)
```

### 6.2 生产环境

```
┌──────────────────────────────────────────────┐
│                Docker Compose                 │
│                                              │
│  ┌────────────┐     ┌────────────────────┐  │
│  │   Nginx    │     │   FastAPI App      │  │
│  │   (反向代理 │────→│   (uvicorn)        │  │
│  │   + 静态资源│     │   port: 8000       │  │
│  │   + HTTPS) │     └────────┬───────────┘  │
│  │   port: 80 │              │               │
│  │   port:443 │     ┌────────┴───────────┐  │
│  └────────────┘     │  SQLite Volume     │  │
│                     │  /data/novel.db    │  │
│                     └────────────────────┘  │
│                                              │
│  ┌────────────┐ (可选)                       │
│  │   Redis    │                              │
│  │   port:6379│                              │
│  └────────────┘                              │
└──────────────────────────────────────────────┘
```

### 6.3 云端同步（可选扩展）

```
本地 SQLite ←── Sync Service ──→ 云端数据库 (PostgreSQL / Supabase)
                  │
                  ├── 增量同步 (基于 timestamp)
                  ├── 冲突检测与合并
                  └── 离线队列 (网络恢复后自动同步)
```

---

## 7. 安全设计

### 7.1 数据安全

| 措施 | 说明 |
|------|------|
| API 密钥加密 | AES-256-GCM 加密存储，服务端主密钥通过环境变量注入 |
| 传输加密 | 生产环境强制 HTTPS，开发环境 HTTP |
| 数据隔离 | 每个项目独立数据空间，API 路径强制 project_id 校验，跨项目不可访问 |
| 本地存储加密 | 浏览器 IndexedDB 数据可选加密（Web Crypto API） |

### 7.2 请求安全

| 措施 | 说明 |
|------|------|
| CORS 策略 | 严格限制允许的源 |
| 请求频率限制 | 后端 Rate Limiter，防止 LLM API 滥用 |
| 输入校验 | Pydantic 模型严格校验所有输入 |
| SQL 注入防护 | SQLAlchemy ORM 参数化查询 |
| 项目归属校验 | 所有项目级 API 自动校验资源是否属于指定项目 |

### 7.3 隐私保护

- 用户创作内容默认仅存储在本地
- LLM 请求日志不记录完整内容，仅记录元数据（时间、token 用量）
- 云端同步为可选功能，需用户显式开启
- 支持数据导出与完整删除

---

## 8. 性能优化策略

### 8.1 LLM 交互优化

| 策略 | 说明 |
|------|------|
| 流式输出 | SSE 流式传输，首字延迟 < 500ms |
| 上下文压缩 | 长文本自动摘要，减少 Token 消耗 |
| 请求缓存 | 相同 Prompt 短时间内返回缓存结果 |
| 并行请求 | 一致性分析多维度并行调用 LLM |
| 智能重试 | 指数退避重试，最大 3 次 |

### 8.2 前端性能优化

| 策略 | 说明 |
|------|------|
| 虚拟滚动 | 章节列表、人物列表长列表虚拟化 |
| 懒加载 | 路由级代码分割，按需加载 |
| 防抖节流 | 编辑器自动保存防抖、搜索输入节流 |
| Web Worker | 一致性规则检测移至 Worker 线程 |
| 增量渲染 | 大纲树增量更新，避免全量重绘 |

### 8.3 后端性能优化

| 策略 | 说明 |
|------|------|
| 异步 I/O | FastAPI 全异步，httpx 异步调用 LLM |
| 连接池 | SQLAlchemy 异步连接池 |
| 响应压缩 | Gzip 中间件 |
| 分页查询 | 大纲节点、章节列表分页返回 |

---

## 9. 扩展性设计

### 9.1 LLM Provider 扩展

通过抽象 `LLMProvider` 接口，支持快速接入新的 LLM 服务：

```python
class LLMProvider(ABC):
    @abstractmethod
    async def chat_completion(self, messages, **kwargs) -> str: ...

    @abstractmethod
    async def stream_completion(self, messages, **kwargs) -> AsyncIterator[str]: ...
```

内置实现：`DeepSeekProvider`、`OpenAICompatibleProvider`（兼容所有 OpenAI API 格式的服务）。

### 9.2 编辑器扩展

TipTap 编辑器支持自定义 Extension，可扩展：
- AI 续写悬浮菜单
- 人物标注高亮
- 伏笔标记
- 时间线标记

### 9.3 导出格式扩展

通过 `Exporter` 接口支持新增导出格式：

```python
class Exporter(ABC):
    @abstractmethod
    async def export(self, project_id, options) -> bytes: ...
```

内置实现：`TxtExporter`、`MarkdownExporter`、`DocxExporter`。

---

## 10. 项目目录结构

```
narrative-forge/
├── docs/                          # 项目文档
│   ├── architecture.md            # 架构设计文档（本文件）
│   ├── api.md                     # REST API 端点详细参考
│   ├── implementation.md          # 编码实现细节
│   ├── data-model.md              # 数据模型（ER 图、表字段）
│   ├── development.md             # 开发指南（如何扩展）
│   ├── deployment.md              # 部署文档
│   └── troubleshooting.md         # 排错与已知 bug
├── frontend/                      # 前端项目（React 19 + TS + Vite）
│   ├── public/
│   ├── src/
│   │   ├── modules/               # 功能模块
│   │   │   ├── project/           # 项目列表
│   │   │   ├── workspace/         # 项目内布局（侧边栏 + Outlet）
│   │   │   ├── outline/           # 大纲编辑器
│   │   │   ├── character/         # 人物管理（含 RelationshipGraph）
│   │   │   ├── chapter/           # 章节编辑器
│   │   │   ├── novel/             # 一键整本写（流式续写）
│   │   │   ├── consistency/       # 一致性报告
│   │   │   ├── export/            # 导出
│   │   │   └── llm-config/        # LLM 配置（全局）
│   │   ├── components/ui/         # 通用 UI（Button / Input / Modal / Select）
│   │   ├── stores/                # Zustand：project/outline/chapter/llmConfig
│   │   ├── services/api.ts        # 所有后端 API 调用的唯一入口
│   │   ├── types/index.ts         # TS 类型（与后端 schema 对应）
│   │   ├── utils/                 # localStorage / debounce
│   │   ├── Layout.tsx             # 全局布局
│   │   ├── App.tsx                # 路由配置
│   │   └── main.tsx               # 入口
│   ├── index.html
│   ├── vite.config.ts             # 含 /api 代理
│   └── package.json
├── backend/                       # 后端项目（Python 3.11+ / FastAPI / SQLAlchemy 2）
│   ├── app/
│   │   ├── api/v1/                # API 路由
│   │   │   ├── projects.py        # /api/v1/projects
│   │   │   ├── outlines.py        # /api/v1/projects/{pid}/outlines
│   │   │   ├── characters.py      # /api/v1/projects/{pid}/characters
│   │   │   ├── chapters.py        # /api/v1/projects/{pid}/chapters
│   │   │   ├── analysis.py        # /api/v1/projects/{pid}/analysis
│   │   │   ├── export.py          # /api/v1/projects/{pid}/export
│   │   │   └── llm_config.py      # /api/v1/llm-configs（全局）
│   │   ├── core/                  # config / security / exceptions
│   │   ├── models/                # SQLAlchemy 模型（project/outline/character/chapter/llm_config/analysis/base）
│   │   ├── schemas/               # Pydantic 模式（请求/响应）
│   │   ├── services/              # 业务逻辑（project/outline/character/chapter/consistency/export/llm_orchestrator）
│   │   ├── llm/                   # LLM 集成
│   │   │   ├── providers/         # base / deepseek / openai / anthropic / google / openai_compatible
│   │   │   ├── prompts/           # outline / chapter / consistency / novel_write
│   │   │   └── rate_limiter.py
│   │   ├── db/                    # session / init_db
│   │   └── main.py                # FastAPI 入口 + 路由注册
│   ├── tests/test_api.py          # 基础集成测试
│   ├── pyproject.toml
│   ├── .env.example               # 环境变量示例；本地 .env 不提交
│   └── data/.gitkeep              # 空数据目录占位；数据库和上传文件不提交
├── OPEN_SOURCE.md
└── README.md
```
