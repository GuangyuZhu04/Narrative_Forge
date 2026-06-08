# Novel Writing Agent — 数据模型

> 本文档描述本项目的数据库结构、表字段、关系与索引策略。

---

## 1. 总览

### 1.1 设计原则

1. **Project 是顶层资源**：所有业务实体（Outline / Character / Chapter / AnalysisReport）必须通过 `project_id` 外键挂到 Project 下。
2. **级联删除**：`Project` 删了，所有子资源一起删，简化数据生命周期管理。
3. **UUID 主键**：避免枚举攻击（ID 不可预测）+ 适合分布式生成。
4. **JSON 字段保留灵活**：人物画像、章节元数据等用 JSON 存，由 LLM 决定内部结构。
5. **没有物理外键约束强制**：SQLite 启用外键需要 `PRAGMA foreign_keys = ON`，项目目前没强制（但 SQLAlchemy 模型里有 `ForeignKey(...)` 声明）。

### 1.2 完整 ER 图

```
┌────────────────────┐
│      projects      │
│ (Project 模型)     │
│ id PK (UUID)       │
│ name               │
│ description        │
│ genre              │
│ status             │
│ word_count_target  │
│ settings           │
│ created_at         │
│ updated_at         │
└─────────┬──────────┘
          │ 1
          │
          ├────────────────────────────────────────────────────┐
          │ N                                                  │
          ▼                                                    ▼
┌────────────────────┐                              ┌──────────────────────┐
│      outlines      │                              │      characters      │
│ id PK              │                              │ id PK                │
│ project_id FK ────►│                              │ project_id FK ──────►│
│ title              │                              │ name                 │
│ description        │                              │ aliases (JSON)       │
│ version            │                              │ avatar_url           │
│ created_at         │                              │ basic_info (JSON)    │
│ updated_at         │                              │ personality (JSON)   │
└─────────┬──────────┘                              │ growth_arc (JSON)    │
          │ 1                                        │ notes                │
          │                                          │ created_at           │
          │ N                                        │ updated_at           │
          ▼                                          └─────────┬────────────┘
┌────────────────────┐                                        │ 1
│   outline_nodes    │                                        │
│ id PK              │                                        │
│ outline_id FK ────►│                              ┌─────────┴──────────┐
│ parent_id FK ──┐   │                              │ N                  │
│ (self-ref)     │   │                              ▼                    ▼
│ node_type      │   │              ┌─────────────────────────┐  ┌──────────────────┐
│ title          │   │              │ character_relationships │  │     chapters     │
│ summary        │   │              │ id PK                   │  │ id PK            │
│ sort_order     │   │              │ project_id FK ────────► │  │ project_id FK ► │
│ metadata (JSON)│   │              │ source_id FK ────────► │  │ outline_node_id  │
│ llm_generated  │   │              │ target_id FK ────────► │  │ title            │
│ created_at     │   │              │ relationship_type      │  │ content          │
│ updated_at     │   │              │ description             │  │ summary          │
└────────────────┘   │              │ intensity (1-10)        │  │ sort_order       │
          ▲          │              │ start_chapter           │  │ status           │
          └──────────┘              │ end_chapter             │  │ word_count       │
                                    │ metadata (JSON)         │  │ created_at       │
                                    │ created_at              │  │ updated_at       │
                                    │ updated_at              │  └────────┬─────────┘
                                    └─────────────────────────┘           │ 1
                                                                         │ N
                                                                         ▼
                                                            ┌──────────────────────┐
                                                            │  chapter_versions    │
                                                            │ id PK                │
                                                            │ chapter_id FK        │
                                                            │ version_number       │
                                                            │ content (full text)  │
                                                            │ word_count           │
                                                            │ change_summary       │
                                                            │ created_at           │
                                                            └──────────────────────┘

┌──────────────────────┐
│  analysis_reports    │                ┌──────────────────────┐
│ id PK                │                │     llm_configs      │
│ project_id FK ──────►│                │ id PK                │
│ chapter_id FK ──────►│                │ provider             │
│ analysis_type        │                │ api_key_encrypted    │
│ status               │                │ base_url             │
│ issues (JSON)        │                │ model_name           │
│ suggestions (JSON)   │                │ default_params (JSON)│
│ score (Float)        │                │ rate_limit (JSON)    │
│ created_at           │                │ is_active            │
│ updated_at           │                │ created_at           │
└──────────────────────┘                │ updated_at           │
                                        └──────────────────────┘
                                       （独立全局表，无 project_id）
```

---

## 2. 公共字段与 Mixin

所有表都继承两个 Mixin（`backend/app/models/base.py`）：

### 2.1 `UUIDMixin`

```python
id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid.uuid4()))
```

- 类型：UUID 字符串
- 默认值：自动生成
- 在 URL / API 引用里都是这个 id

### 2.2 `TimestampMixin`

```python
created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

- 服务端时间戳，**不依赖应用层**（避免应用服务器时钟漂移）
- `updated_at` 在每次 UPDATE 时自动更新

---

## 3. 表详解

### 3.1 `projects` — 写作项目（顶层）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | UUID | 自动 | 主键 |
| `name` | VARCHAR(200) | ✓ | 项目名 |
| `description` | TEXT | - | 项目描述 |
| `genre` | VARCHAR(100) | - | 体裁（玄幻/科幻/都市等） |
| `status` | VARCHAR(20) | - | `draft` / `in_progress` / `completed`，默认 `draft` |
| `word_count_target` | INT | - | 目标字数 |
| `settings` | TEXT | - | 项目级设置（JSON 字符串） |
| `created_at` | DateTime | 自动 | - |
| `updated_at` | DateTime | 自动 | - |

**关系**：

```python
outlines = relationship("Outline", cascade="all, delete-orphan")
chapters = relationship("Chapter", cascade="all, delete-orphan")
characters = relationship("Character", cascade="all, delete-orphan")
analysis_reports = relationship("AnalysisReport", cascade="all, delete-orphan")
```

**索引**：

- `id` 主键索引
- `status`（按状态筛选项目时用）

---

### 3.2 `outlines` — 大纲

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | UUID | 自动 | - |
| `project_id` | UUID (FK) | ✓ | 所属项目 |
| `title` | VARCHAR(300) | ✓ | 大纲标题 |
| `description` | TEXT | - | 描述 |
| `version` | INT | - | 大纲版本号（暂未启用多版本管理） |
| `created_at` | DateTime | 自动 | - |
| `updated_at` | DateTime | 自动 | - |

**注意**：一个项目可以有多份大纲（比如"主大纲"+"备选大纲"），但当前 UI 主要展示第一份。

### 3.3 `outline_nodes` — 大纲节点（树形）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | UUID | 自动 | - |
| `outline_id` | UUID (FK) | ✓ | 所属大纲 |
| `parent_id` | UUID (FK, self) | - | 父节点，null = 根 |
| `node_type` | VARCHAR(20) | ✓ | `VOLUME` / `CHAPTER` / `SCENE` / `PLOT_POINT` / `KEY_EVENT` |
| `title` | VARCHAR(300) | ✓ | 节点标题 |
| `summary` | TEXT | - | 节点概述 |
| `sort_order` | INT | - | 同级排序，默认 0 |
| `metadata_` | JSON (`metadata`) | - | 元数据（情感基调、时间设定、地点等） |
| `llm_generated` | BOOL | - | 是否 LLM 生成的，默认 `false` |
| `created_at` | DateTime | 自动 | - |
| `updated_at` | DateTime | 自动 | - |

**树形层级**：

```
VOLUME (卷)
  └── CHAPTER (章)
        └── SCENE (场)
              └── PLOT_POINT / KEY_EVENT (情节点 / 关键事件)
```

**前端别名**：

后端 ORM 字段叫 `metadata_`（避免和 SQLAlchemy 的 `MetaData` 类冲突），实际数据库列名是 `metadata`，Pydantic schema 暴露为 `metadata`。

### 3.4 `characters` — 人物

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | UUID | 自动 | - |
| `project_id` | UUID (FK) | ✓ | 所属项目 |
| `name` | VARCHAR(100) | ✓ | 姓名 |
| `aliases` | JSON | - | 别名列表，如 `["舰长", "老林"]` |
| `avatar_url` | VARCHAR(500) | - | 头像 URL（前端暂未上传） |
| `basic_info` | JSON | - | 基本信息（年龄/性别/职业/外貌/背景） |
| `personality` | JSON | - | 性格（性格特征/MBTI/价值观/缺陷/说话风格） |
| `growth_arc` | JSON | - | 成长弧线（初始状态/发展/转折/最终） |
| `notes` | TEXT | - | 备注 |
| `created_at` | DateTime | 自动 | - |
| `updated_at` | DateTime | 自动 | - |

**JSON 字段约定**：

`basic_info` / `personality` / `growth_arc` 的具体结构由 LLM 决定（看 `backend/app/llm/prompts/chapter.py` 的 `CHARACTER_GENERATE_SYSTEM`），是中文键的 dict：

```json
{
  "basic_info": {
    "年龄": "28",
    "性别": "男",
    "职业": "剑客",
    "背景": "..."
  },
  "personality": {
    "性格特征": "外冷内热",
    "价值观": "...",
    "习惯": "...",
    "缺陷": "..."
  },
  "growth_arc": {
    "初始状态": "...",
    "发展方向": "...",
    "转折点": "...",
    "最终状态": "..."
  }
}
```

**`CHARACTER_IMPORT_SYSTEM`** 用的也是这套中文 key。一键导入接口解析时也按这个结构匹配。

### 3.5 `character_relationships` — 人物关系

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | UUID | 自动 | - |
| `project_id` | UUID (FK) | ✓ | 所属项目（冗余，方便按项目查） |
| `source_id` | UUID (FK → characters) | ✓ | 源人物 |
| `target_id` | UUID (FK → characters) | ✓ | 目标人物 |
| `relationship_type` | VARCHAR(30) | ✓ | `FAMILY` / `FRIEND` / `ENEMY` / `LOVER` / `MENTOR` / `SUBORDINATE` / `ALLY` / `RIVAL` / `OTHER` |
| `description` | TEXT | - | 关系描述 |
| `intensity` | INT | - | 关系强度 1-10，默认 5 |
| `start_chapter` | VARCHAR(50) | - | 关系起始章节 |
| `end_chapter` | VARCHAR(50) | - | 关系结束章节 |
| `metadata_` | JSON (`metadata`) | - | 元数据 |

**约束**：

- 没有禁止 `source_id == target_id`（自环）—— 应用层校验
- 同一对 `(source, target)` 可以有多条不同类型的关系（少见但允许）
- 删除 character 时级联删除相关 relationships（双向 cascade）

### 3.6 `chapters` — 章节

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | UUID | 自动 | - |
| `project_id` | UUID (FK) | ✓ | 所属项目 |
| `outline_node_id` | UUID (FK → outline_nodes) | - | 关联的大纲节点（删除大纲节点时 SET NULL，章节保留） |
| `title` | VARCHAR(300) | ✓ | 章节标题 |
| `content` | TEXT | - | 章节内容（HTML，来自 TipTap） |
| `summary` | TEXT | - | 摘要 |
| `sort_order` | INT | - | 章节排序 |
| `status` | VARCHAR(20) | - | `draft` / `in_progress` / `completed` / `revised`，默认 `draft` |
| `word_count` | INT | - | 字数（中文按汉字数） |
| `created_at` | DateTime | 自动 | - |
| `updated_at` | DateTime | 自动 | - |

**注意**：

- `content` 存的是 **HTML 字符串**（不是 Markdown / 富文本 JSON），由 TipTap 输出
- `word_count` 由前端或 `novel-write-stream` 路由计算（用正则 `r'[\u4e00-\u9fff]'` 数中文字符）

### 3.7 `chapter_versions` — 章节版本快照

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | UUID | 自动 | - |
| `chapter_id` | UUID (FK) | ✓ | 所属章节 |
| `version_number` | INT | ✓ | 版本号（自增） |
| `content` | TEXT | ✓ | 完整内容 |
| `word_count` | INT | ✓ | 字数 |
| `change_summary` | TEXT | - | 变更说明 |
| `created_at` | DateTime | 自动 | - |

**版本管理**：

- 用户主动调「保存版本」接口创建快照
- 不自动保存（避免无限增长）
- `version_number` 在 `chapter_id` 内单调递增
- 删除 chapter 时级联删除所有 version

### 3.8 `analysis_reports` — 一致性分析报告

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | UUID | 自动 | - |
| `project_id` | UUID (FK) | ✓ | 所属项目 |
| `chapter_id` | UUID (FK → chapters) | - | 被分析的章节（删除时 SET NULL） |
| `analysis_type` | VARCHAR(50) | ✓ | `character` / `plot` / `timeline` / `overall` |
| `status` | VARCHAR(20) | - | `pending` / `completed` / `error`，默认 `pending` |
| `issues` | JSON | - | 问题列表 |
| `suggestions` | JSON | - | 建议列表 |
| `score` | FLOAT | - | 评分（0-100） |
| `created_at` | DateTime | 自动 | - |
| `updated_at` | DateTime | 自动 | - |

**注意**：

- `issues` / `suggestions` 是 JSON list，**结构由 LLM 决定**
- 当前实现（`consistency_service.py`）是把多维度结果合并写入一条 report，而不是每个维度一条

### 3.9 `llm_configs` — LLM 配置（全局）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | UUID | 自动 | - |
| `provider` | VARCHAR(50) | ✓ | `deepseek` / `openai_compatible` |
| `api_key_encrypted` | VARCHAR | ✓ | **加密后**的 API 密钥（base64 密文） |
| `base_url` | VARCHAR(500) | ✓ | API base URL |
| `model_name` | VARCHAR(100) | ✓ | 模型名 |
| `default_params` | JSON (dict) | - | 默认 LLM 参数（temperature/top_p/max_tokens 等），默认 `{}` |
| `rate_limit` | JSON | - | 频率限制（requests_per_minute/tokens_per_minute/max_concurrent） |
| `is_active` | BOOL | - | 是否启用，默认 `true` |
| `created_at` | DateTime | 自动 | - |
| `updated_at` | DateTime | 自动 | - |

**安全细节**：

- `api_key_encrypted` 实际是 `base64(salt + nonce + ciphertext)`，使用 AES-256-GCM 加密，主密钥来自 `SECRET_KEY`（见 `backend/app/core/security.py`）
- API 返回时 `api_key_encrypted` 字段被 mask 成 `****masked****`（见 `backend/app/api/v1/llm_config.py:19` 的 `MASKED_KEY`）
- 数据库**永远不存明文 key**
- 详见 `docs/deployment.md` 第 3 节

---

## 4. 关系与级联

### 4.1 级联删除矩阵

| 父表 | 子表 | 级联行为 |
|------|------|----------|
| Project | Outline | CASCADE DELETE（项目删了大纲也删） |
| Project | Character | CASCADE DELETE |
| Project | Chapter | CASCADE DELETE |
| Project | AnalysisReport | CASCADE DELETE |
| Outline | OutlineNode | CASCADE DELETE |
| OutlineNode (parent) | OutlineNode (child) | CASCADE DELETE（删父节点删子节点） |
| Character | CharacterRelationship (source) | CASCADE DELETE |
| Character | CharacterRelationship (target) | CASCADE DELETE |
| Chapter | ChapterVersion | CASCADE DELETE |
| Chapter | AnalysisReport | SET NULL（删章节保留报告） |
| OutlineNode | Chapter | SET NULL（删大纲节点保留章节） |

### 4.2 为什么 `Chapter` 引用 `OutlineNode` 用 SET NULL？

让"已写好的章节"独立于大纲存在——大纲调整不影响已有内容。代价是章节可能"悬空"（不挂在任何大纲节点上），应用层需要在 UI 上提示。

---

## 5. 索引策略

| 表 | 索引字段 | 用途 |
|----|----------|------|
| `projects` | `status` | 按状态筛选项目列表 |
| `outlines` | `project_id` | 查某项目下所有大纲 |
| `outline_nodes` | `outline_id` | 查大纲节点 |
| `outline_nodes` | `parent_id` | 查子节点（树形遍历） |
| `outline_nodes` | `(outline_id, sort_order)` | 排序展示 |
| `characters` | `project_id` | 查项目下所有人物 |
| `character_relationships` | `project_id` | 查项目下所有关系 |
| `character_relationships` | `(source_id, target_id)` | 查反向关系 |
| `chapters` | `project_id` | 查项目章节 |
| `chapters` | `(project_id, sort_order)` | 章节排序 |
| `chapter_versions` | `chapter_id` | 查版本列表 |
| `chapter_versions` | `(chapter_id, version_number)` UNIQUE | 版本号唯一性 |
| `analysis_reports` | `project_id` | 查项目报告 |
| `analysis_reports` | `chapter_id` | 查章节报告 |
| `llm_configs` | `is_active` | 找激活的配置 |

> **TODO**：当前 SQLAlchemy 还没显式建这些复合索引（只有主键）。SQLite 也会自动建单列索引。等切到 PostgreSQL 时应该在模型上加 `index=True` / `Index(...)`。

---

## 6. 数据迁移

⚠️ **本项目目前没有用 Alembic**。`backend/app/main.py` 的 `lifespan` 在每次启动时跑 `Base.metadata.create_all`，**仅对新表有效**，不会 ALTER 已存在的表。

**后果**：

- 加新表：OK，启动自动建
- 加新字段到现有表：**不会生效**，老表保持原 schema
- 改字段类型/长度：**不会生效**

**短期手动迁移方案**（生产前必做）：

```python
# 在 main.py 启动时跑一次
async with engine.begin() as conn:
    # 加字段示例
    await conn.execute(text("ALTER TABLE characters ADD COLUMN new_field VARCHAR(100)"))
    # 加索引示例
    await conn.execute(text("CREATE INDEX idx_chapters_project_sort ON chapters(project_id, sort_order)"))
```

**长期方案**（TODO）：引入 Alembic。

---

## 7. 数据生命周期

| 操作 | 影响 |
|------|------|
| 创建项目 | 写 `projects` 1 条 |
| 删除项目 | 删 `projects` 1 条 + 级联删所有 outline/character/chapter/analysis_report |
| 改 LLM 配置 | 原地 UPDATE；`updated_at` 刷新；**provider 缓存可能不刷新**（见 troubleshooting #9） |
| 保存章节版本 | 写 `chapter_versions` 1 条；`version_number` = 同 chapter 内 max + 1 |
| 创建分析报告 | 写 `analysis_reports` 1 条（流式接口在流完后写一次） |
| 一致性分析 | 写 1 条 `analysis_reports`（多维度结果合并） |

**典型数据增长**：

- 一本 30 万字小说 ≈ 100 章
- 每个章节每次手动保存版本 ≈ 100-300 条 chapter_versions
- 每次一致性分析 ≈ 1 条 analysis_reports
- 评估数据量：每本书 ~1-5 万行（极小，SQLite 轻松胜任）

---

## 8. 备份与导出

- **全量备份**：复制 `data/novel_agent.db`（见 `docs/deployment.md` 第 4 节）
- **数据导出**：`backend/app/services/export_service.py` 支持导出整个项目为 TXT / Markdown / DOCX（见 API 文档）
- **数据导入**：**没有**导入接口（TODO）

---

## 9. 常见查询模式

```sql
-- 某项目下所有章节（按顺序）
SELECT * FROM chapters WHERE project_id = ? ORDER BY sort_order;

-- 某项目下所有大纲节点（树形）
SELECT * FROM outline_nodes
WHERE outline_id IN (SELECT id FROM outlines WHERE project_id = ?)
ORDER BY sort_order;

-- 某人物的所有关系
SELECT * FROM character_relationships
WHERE source_id = ? OR target_id = ?;

-- 某项目的所有分析报告
SELECT * FROM analysis_reports
WHERE project_id = ?
ORDER BY created_at DESC;

-- 当前激活的 LLM 配置（前端 getActiveLLMConfigId 用）
SELECT * FROM llm_configs WHERE is_active = 1 LIMIT 1;
```

这些查询在 `backend/app/services/*.py` 里都有对应实现，可以参考。
