# Novel Writing Agent — 开发指南

> 本文档面向参与本项目二次开发的工程师，覆盖开发环境、代码组织、扩展点（如何新增 LLM Provider / API 端点 / 前端页面 / Prompt 模板），以及调试技巧。

---

## 1. 开发环境

### 1.1 依赖

| 工具 | 版本 | 说明 |
|------|------|------|
| Python | 3.11+ | 后端 |
| Node.js | 18+ | 前端 |
| npm | 9+ | 前端包管理 |
| Git | 2.x | - |

### 1.2 首次拉取与启动

```bash
git clone <repo-url>
cd narrative-forge

# 后端
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"
cp .env.example .env             # 改 SECRET_KEY / DATABASE_URL
python -m uvicorn app.main:app --reload

# 前端（另开终端）
cd ../frontend
npm install
npm run dev
```

启动后端后访问 `http://localhost:8000/docs` 可看自动生成的 OpenAPI 文档（Swagger UI），所有端点的请求/响应 schema 都在那儿，是写前端调用代码最准确的参考。

### 1.3 推荐的 IDE 配置

- **后端**：VSCode + Python 扩展；启用 Pylance；类型检查 `mypy --strict` 模式
- **前端**：VSCode + TS 语言服务 + ESLint 插件
- **后端格式化**：`ruff format` + `ruff check`
- **前端格式化**：`prettier`（如果有）

---

## 2. 代码组织速记

### 2.1 后端分层

```
backend/app/
├── api/v1/          # 路由层：HTTP 入口，负责参数解析 + 调 service + 返回响应
├── services/        # 业务逻辑层：所有"怎么做"的代码都在这里
├── models/          # SQLAlchemy ORM 模型（表结构）
├── schemas/         # Pydantic 模型（请求/响应校验）
├── llm/             # LLM 抽象层
│   ├── providers/   # 具体 LLM 服务商实现
│   ├── prompts/     # Prompt 模板（System + User）
│   └── rate_limiter.py
├── core/            # 基础设施：配置、安全、异常
├── db/              # 异步 session 工厂
└── main.py          # FastAPI 入口 + 路由注册
```

**调用链**：`api/v1/*.py` → `services/*.py` → `models/*` + `llm_orchestrator`

> Service 层是"业务大脑"，永远不要把数据库操作或 LLM 调用写在 API 路由里。

### 2.2 前端分层

```
frontend/src/
├── modules/         # 功能模块（一个文件夹对应一个完整功能页）
│   ├── project/     # 项目列表
│   ├── workspace/   # 项目内布局（侧边栏 + Outlet）
│   ├── outline/     # 大纲
│   ├── character/   # 人物
│   ├── chapter/     # 章节
│   ├── novel/       # 一键写整本
│   ├── consistency/ # 一致性
│   ├── export/      # 导出
│   └── llm-config/  # LLM 配置（全局）
├── components/ui/   # 通用 UI 组件（Button / Input / Modal / Select）
├── stores/          # Zustand 状态（一个领域一个 store）
├── services/api.ts  # 所有后端 API 调用的唯一入口
├── types/           # TypeScript 类型（与后端 schemas 1:1）
├── utils/           # 工具函数（localStorage、debounce）
├── App.tsx          # 路由配置
└── main.tsx         # 入口
```

> `services/api.ts` 是**唯一允许直接用 axios** 的地方。其他文件都应该从这引入 `*Api` 对象。

### 2.3 关键设计原则

1. **Project 是一切业务资源的父级**。所有业务 API 都嵌套在 `/projects/{project_id}/` 下，新增业务资源时遵循这个约定。
2. **LLM 调用必须走 orchestrator**。不要在 service 里直接 import provider。
3. **API 密钥不离开后端**。前端永远不持有明文 key，只持有 `config_id`。
4. **JSON 字段尽量用 dict[str, Any]**。本项目大量用了 `basic_info`、`personality`、`growth_arc`、`metadata` 等 JSON 字段，schema 故意保持灵活，由 LLM 决定内部结构。

---

## 3. 扩展点

### 3.1 新增 LLM Provider

适用场景：要接入 OpenAI / Claude / Gemini / 国产其他厂商。

LLM Provider 的设计原则是**继承 + 重写**：

1. 在 `backend/app/llm/providers/` 新建文件，如 `openai.py`：

```python
import httpx
from typing import AsyncIterator
from .base import LLMProvider
from app.core.security import decrypt_api_key


class OpenAIProvider(LLMProvider):
    API_BASE = "https://api.openai.com/v1"

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = decrypt_api_key(config["api_key_encrypted"])
        self.model = config.get("model_name", "gpt-4o")
        self.base_url = config.get("base_url", self.API_BASE)
        # ⚠️ dict.get(key, default) 在 key 存在但值为 None 时不返回 default
        # 必须用 `or {}` 才能兜底 None
        self.default_params = config.get("default_params") or {}

    async def chat_completion(self, messages, **kwargs) -> str:
        payload = self._build_payload(messages, stream=False, **kwargs)
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def stream_completion(self, messages, **kwargs) -> AsyncIterator[str]:
        # 实现 SSE 解析
        ...

    def _build_payload(self, messages, stream, **kwargs) -> dict:
        params = {**(self.default_params or {}), **kwargs}
        return {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            **{k: v for k, v in params.items() if v is not None},
        }

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def validate_config(self) -> bool:
        return bool(self.api_key and self.model)
```

2. 在 `backend/app/services/llm_orchestrator.py` 的 `PROVIDER_MAP` 里注册：

```python
PROVIDER_MAP = {
    "deepseek": DeepSeekProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "openai": OpenAIProvider,   # ← 新增
}
```

3. 在 `backend/app/schemas/llm_config.py` 的 `LLMConfigCreate` / `LLMConfigUpdate` 的 `pattern` 里加上新 provider：

```python
provider: str = Field(..., pattern="^(deepseek|openai_compatible|openai)$")
```

4. 前端 `frontend/src/modules/llm-config/LLMConfigPanel.tsx` 的 provider 下拉框加上新选项。

5. 写完跑一下集成测试：在「设置」里添加配置、点「测试连接」。

> 💡 实际上 OpenAI / Azure / 一堆国产模型都兼容 OpenAI Chat Completion 协议。如果只想换 base_url 和 model_name，**直接用 `openai_compatible` 即可，不用新增 provider 类**。

### 3.2 新增后端 API 端点

适用场景：比如要加一个"全文搜索章节"接口。

**步骤**：

1. **确定归属**：是项目级（嵌套在 `/projects/{pid}/...`）还是全局（独立路径）。
2. **写 schema**（如有必要）：`backend/app/schemas/<resource>.py` 加 `XxxCreate / XxxUpdate / XxxResponse`。
3. **写 service 方法**：`backend/app/services/<resource>_service.py` 加新方法，**所有 DB 操作走 service，不要在 API 层直接用 `db.execute`**。
4. **写路由**：`backend/app/api/v1/<resource>.py` 加新 `@router.<method>(...)`，使用 `verify_project_access` 依赖做项目校验（如果是项目级）。
5. **在 main.py 注册路由**：如果新建了文件，需要在 `app.include_router(...)` 注册；现有文件直接生效。
6. **前端**：在 `frontend/src/services/api.ts` 的 `*Api` 对象里加方法，类型从 `@/types` 取。
7. **测试**：访问 `/docs` 看 OpenAPI 是否正确展示。

**模板**（项目级 POST 端点）：

```python
# backend/app/api/v1/<resource>.py
@router.post("/<path>", response_model=<ResponseSchema>, status_code=201)
async def my_endpoint(
    project_id: str,
    data: <RequestSchema>,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),  # 项目级必须有
):
    result = await <resource>_service.do_something(
        db, project_id, data.field1, data.field2
    )
    return result
```

### 3.3 新增前端页面

适用场景：要加一个新功能模块，比如"灵感收集"。

**步骤**：

1. 在 `frontend/src/modules/<feature>/` 建文件夹。
2. 写主组件 `<Feature>.tsx`，从 `@/services/api` 引入 `featureApi`，本地用 `useState/useEffect` 即可，**复杂跨页状态才上 Zustand**。
3. 如果需要嵌入到项目工作区：在 `frontend/src/App.tsx` 加 `<Route path="<feature>" element={<<Feature> />} />`，**作为 `<Route path="/projects/:projectId" element={<ProjectWorkspace />}>` 的子路由**。
4. 如果是全局页面（独立于项目）：加 `<Route path="/<feature>" element={<<Feature> />} />` 平级。
5. 在 `frontend/src/modules/workspace/ProjectWorkspace.tsx` 的 `workspaceNavItems` 数组里加上入口（侧边栏导航）。
6. 通用 UI 复用 `components/ui/{Button,Input,Modal,Select}`，不要重复造。

### 3.4 新增 Prompt 模板

适用场景：要新增一个 AI 操作（比如"生成章末钩子"）。

**步骤**：

1. 在 `backend/app/llm/prompts/<module>.py` 加 `XXX_SYSTEM` / `XXX_USER` 常量（必须是 raw string，保留 `{variable}` 占位符）。
2. 在 service 里用 `.format(variable=value)` 注入：

```python
messages = [
    {"role": "system", "content": XXX_SYSTEM},
    {"role": "user", "content": XXX_USER.format(**params)},
]
```

3. **写 Prompt 的几个原则**：
   - System prompt 明确角色 + 输出格式约束（最好给出 JSON schema 示例）
   - User prompt 包含**足够的上下文**（人物、前文、要求），但不堆砌
   - 涉及 JSON 输出时，提醒"只返回 JSON，不要解释"
   - 中文场景下提醒模型"使用中文输出"

### 3.5 新增数据模型

适用场景：新增一种资源，比如"灵感便签"。

**步骤**：

1. 在 `backend/app/models/<resource>.py` 定义 SQLAlchemy 模型，继承 `UUIDMixin, TimestampMixin, Base`。
2. 在 `backend/app/schemas/<resource>.py` 定义 Pydantic schema（Create / Update / Response）。
3. 在 `backend/app/services/<resource>_service.py` 写业务逻辑。
4. 在 `backend/app/api/v1/<resource>.py` 写路由。
5. 在 `backend/app/main.py` 注册路由。
6. 在 `frontend/src/types/index.ts` 加对应 TS 类型。
7. 在 `frontend/src/services/api.ts` 加 `*Api` 方法。
8. 写前端组件。
9. **数据库迁移**：项目目前用 `Base.metadata.create_all` 自动建表（新模型首次启动会自动建）；**生产环境需要引入 Alembic 做迁移**，本项目尚未接入。

> ⚠️ 给已有表加字段时，**仅靠 create_all 不会 ALTER 已存在的表**。需要手写 SQL 迁移，或者引入 Alembic。

---

## 4. 调试技巧

### 4.1 后端日志

- 默认 `DEBUG=True` 时 SQLAlchemy 会打印所有 SQL 到 stdout，verbose 但有用。
- 关键日志点：`backend/app/services/llm_orchestrator.py` 加临时 print 调试 LLM 调用 payload。
- LLM 错误堆栈：看 `backend/app/llm/providers/deepseek.py` 的 `resp.raise_for_status()`，会抛 `httpx.HTTPStatusError`，里面有完整 status_code + body。

### 4.2 测试单个 LLM 配置

先在前端或 API 中创建 LLM 配置，然后调用测试端点：

```bash
curl -X POST http://localhost:8000/api/v1/llm-configs/<id>/test
```

### 4.3 测试 LLM 响应的 JSON 解析

`backend/app/services/character_service.py` 的 `_extract_json` 是个手写 JSON 提取器，兼容：

- 纯 JSON
- 包裹在 ```json ... ``` 代码块里
- 文本中夹杂 JSON 的情况（提取第一个 `[` 或 `{` 开始到配对结束）

新写一个 service 调 LLM 拿 JSON 的话，**复用这个方法**而不是再写一遍。

### 4.4 前端调试

- React DevTools / Vue DevTools 同款，Zustand 也支持。
- API 调用：打开 DevTools Network 面板，所有请求都带 `/api/v1` 前缀，被 Vite 代理到 `localhost:8000`。
- 错误显示：现在 catch 块统一吐"导入失败，请检查 LLM 配置后重试"——**信息量太低**。调试时建议在 catch 里 `console.error(error.response?.data?.detail || error.message)` 看后端实际报错。

### 4.5 看数据库

SQLite 库文件在 `data/novel_agent.db`，可以用 [DB Browser for SQLite](https://sqlitebrowser.org/) 或 VSCode SQLite 扩展直接打开。

快速看 LLM 配置：

```python
import asyncio
from app.db.session import AsyncSessionLocal
from app.models.llm_config import LLMConfig
from sqlalchemy import select


async def show():
    async with AsyncSessionLocal() as db:
        for c in (await db.execute(select(LLMConfig))).scalars().all():
            print(f"{c.id} | {c.provider} | {c.base_url} | {c.model_name}")
            print(f"  default_params={c.default_params}")
            print(f"  rate_limit={c.rate_limit}")


asyncio.run(show())
```

---

## 5. 常见错误速查

| 现象 | 原因 | 解决 |
|------|------|------|
| 启动报 `unable to open database file` | `DATABASE_URL` 路径不存在或权限不足 | 确认 `data/` 目录已创建 |
| 启动报 `ImportError: cannot import name ...` | 没装 dev 依赖 | `pip install -e ".[dev]"` |
| 前端请求 404 | 后端没启动，或 vite 代理配错 | 检查后端 `localhost:8000` 活着 |
| 前端请求 500 + "导入失败" | 后端 bug | 看后端 stdout / 浏览器 Network 详细 |
| LLM 返回非 JSON | Prompt 约束不够 / 模型能力不足 | 在 Prompt 加"只返回 JSON"；调整 temperature |
| `TypeError: 'NoneType' object is not a mapping` | LLMConfig.default_params 是 None 时被当作 dict 展开 | 见 `docs/troubleshooting.md` 第 1 条 |

---

## 6. CI / 测试

### 6.1 后端

`backend/tests/test_api.py` 有一组基础集成测试（项目 CRUD、人物 CRUD、章节 CRUD、LLM 配置 CRUD）。跑法：

```bash
cd backend
pip install pytest pytest-asyncio httpx
python -m pytest tests/ -v
```

> 注意：测试用的是 `test_db.db`，跑完会清空，不影响 `data/novel_agent.db`。

### 6.2 前端

目前**没有自动化测试**。建议：

- 加 Vitest 做组件单测
- 加 Playwright 做端到端测试
- 至少加 `tsc --noEmit` 到 CI

### 6.3 推荐的 CI 流程（尚未配置）

```yaml
# .github/workflows/ci.yml（建议）
- 后端：lint (ruff) → pytest
- 前端：lint (eslint) → typecheck (tsc) → build
```

---

## 7. 性能与扩展性

- **当前规模**：单用户、本地优先。SQLite + 本地 LLM 配置文件，没有多用户/权限。
- **多用户化**：需要加 user_id 外键、认证中间件、JWT，数据库换 PostgreSQL。
- **横向扩展**：FastAPI 是无状态的，可以直接多 worker（`--workers 4`），但**SQLite 会变成瓶颈**。生产建议用 PostgreSQL 并配连接池。
- **LLM 调用频率**：现在用 `TokenBucketRateLimiter` 做 token bucket，配置在 `llm_configs.rate_limit`。多 LLM 共享同一个 rate_limiter，**目前没有按 config_id 隔离**——若需要，加一个 `dict[str, TokenBucketRateLimiter]` 即可。

---

## 8. 待办 / 技术债

| 序号 | 内容 | 优先级 |
|------|------|--------|
| 1 | 引入 Alembic 做数据库 schema 迁移 | 中 |
| 2 | 前端加 Vitest + Playwright | 中 |
| 3 | 加用户认证与多用户隔离 | 中 |
| 4 | LLM Rate Limiter 按 config_id 隔离 | 低 |
| 5 | 前端错误提示粒度细化（catch 块统一提示） | 低 |
| 6 | `llm_orchestrator` 的 provider 缓存按 `(config_id, model_name)` 维度失效 | 低 |
| 7 | Secret Key 轮换机制（目前改了 SECRET_KEY 旧数据全解不开） | 高（安全） |

详见 `docs/troubleshooting.md`。
