# Novel Writing Agent — 接口文档

## 1. 概述

### 1.1 基本信息

| 项目 | 值 |
|------|-----|
| 基础路径 | `/api/v1` |
| 协议 | HTTP/HTTPS |
| 数据格式 | JSON |
| 字符编码 | UTF-8 |
| 认证方式 | 无（单用户本地应用）；可扩展为 Bearer Token |

### 1.2 路由架构

**核心原则**：写作项目（Project）是所有创作资源的组织单元，大纲、人物、章节、一致性分析等接口均嵌套在项目路径下。

| 资源类型 | 路径前缀 | 说明 |
|----------|----------|------|
| 项目 | `/api/v1/projects` | 顶层资源，独立存在 |
| 大纲 | `/api/v1/projects/{project_id}/outlines` | 嵌套在项目下 |
| 人物 | `/api/v1/projects/{project_id}/characters` | 嵌套在项目下 |
| 章节 | `/api/v1/projects/{project_id}/chapters` | 嵌套在项目下 |
| 一致性分析 | `/api/v1/projects/{project_id}/analysis` | 嵌套在项目下 |
| 导出 | `/api/v1/projects/{project_id}/export` | 嵌套在项目下 |
| LLM 配置 | `/api/v1/llm-configs` | 全局资源，不绑定项目 |

### 1.3 通用响应格式

**成功响应**：

```json
{
  "data": { ... },
  "message": "success"
}
```

**分页响应**：

```json
{
  "data": [...],
  "total": 100,
  "page": 1,
  "page_size": 20
}
```

**错误响应**：

```json
{
  "detail": "错误描述信息",
  "error_code": "ERROR_CODE"
}
```

### 1.4 HTTP 状态码

| 状态码 | 含义 |
|--------|------|
| 200 | 请求成功 |
| 201 | 创建成功 |
| 204 | 删除成功（无返回体） |
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 409 | 资源冲突 |
| 422 | 数据校验失败 |
| 429 | 请求频率超限 |
| 500 | 服务器内部错误 |

### 1.5 通用错误码

| 错误码 | 描述 |
|--------|------|
| VALIDATION_ERROR | 数据校验失败 |
| NOT_FOUND | 资源不存在 |
| PROJECT_NOT_FOUND | 项目不存在 |
| OUTLINE_NOT_FOUND | 大纲不存在 |
| CHAPTER_NOT_FOUND | 章节不存在 |
| CHARACTER_NOT_FOUND | 人物不存在 |
| LLM_CONFIG_NOT_FOUND | LLM 配置不存在 |
| LLM_CONFIG_INACTIVE | LLM 配置未激活 |
| LLM_REQUEST_FAILED | LLM 请求失败 |
| LLM_RATE_LIMITED | LLM 请求频率超限 |
| RESOURCE_PROJECT_MISMATCH | 资源不属于指定项目 |

---

## 2. 项目管理接口

### 2.1 获取项目列表

```
GET /api/v1/projects
```

**查询参数**：

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| status | string | 否 | 按状态筛选：draft / in_progress / completed |
| page | int | 否 | 页码，默认 1 |
| page_size | int | 否 | 每页数量，默认 20 |

**响应示例**：

```json
{
  "data": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "星际迷途",
      "description": "一部关于人类在星际间寻找家园的科幻小说",
      "genre": "科幻",
      "status": "in_progress",
      "word_count_target": 300000,
      "settings": null,
      "created_at": "2026-05-29T10:00:00Z",
      "updated_at": "2026-05-29T15:30:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

### 2.2 获取项目详情

```
GET /api/v1/projects/{project_id}
```

**路径参数**：

| 参数 | 类型 | 描述 |
|------|------|------|
| project_id | string (UUID) | 项目 ID |

**响应示例**：

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "星际迷途",
  "description": "一部关于人类在星际间寻找家园的科幻小说",
  "genre": "科幻",
  "status": "in_progress",
  "word_count_target": 300000,
  "settings": null,
  "created_at": "2026-05-29T10:00:00Z",
  "updated_at": "2026-05-29T15:30:00Z"
}
```

### 2.3 创建项目

```
POST /api/v1/projects
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| name | string | 是 | 项目名称，最大 200 字符 |
| description | string | 否 | 项目描述 |
| genre | string | 否 | 小说体裁，最大 100 字符 |
| word_count_target | integer | 否 | 目标字数 |
| settings | string | 否 | 项目设置（JSON 字符串） |

**请求示例**：

```json
{
  "name": "星际迷途",
  "description": "一部关于人类在星际间寻找家园的科幻小说",
  "genre": "科幻",
  "word_count_target": 300000
}
```

**响应示例**（201 Created）：

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "星际迷途",
  "description": "一部关于人类在星际间寻找家园的科幻小说",
  "genre": "科幻",
  "status": "draft",
  "word_count_target": 300000,
  "settings": null,
  "created_at": "2026-05-29T10:00:00Z",
  "updated_at": "2026-05-29T10:00:00Z"
}
```

### 2.4 更新项目

```
PUT /api/v1/projects/{project_id}
```

**请求体**：同创建项目，所有字段可选。

### 2.5 删除项目

```
DELETE /api/v1/projects/{project_id}
```

**响应**：204 No Content。级联删除项目下所有大纲、人物、章节、分析报告。

---

## 3. 大纲管理接口

> 所有大纲接口均嵌套在项目路径下，`project_id` 为路径参数，自动校验项目存在性。

### 3.1 获取大纲列表

```
GET /api/v1/projects/{project_id}/outlines
```

**路径参数**：

| 参数 | 类型 | 描述 |
|------|------|------|
| project_id | string (UUID) | 项目 ID |

**响应示例**：

```json
{
  "data": [
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "project_id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "星际迷途大纲",
      "description": "三卷本结构",
      "version": 1,
      "created_at": "2026-05-29T10:00:00Z",
      "updated_at": "2026-05-29T10:00:00Z"
    }
  ]
}
```

### 3.2 获取大纲详情（含树结构）

```
GET /api/v1/projects/{project_id}/outlines/{outline_id}/tree
```

**响应示例**：

```json
{
  "outline": {
    "id": "660e8400-e29b-41d4-a716-446655440001",
    "title": "星际迷途大纲",
    "description": "三卷本结构",
    "version": 1
  },
  "tree": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440010",
      "node_type": "VOLUME",
      "title": "第一卷：启航",
      "summary": "人类决定离开地球，踏上星际旅途",
      "sort_order": 0,
      "metadata": {
        "emotional_tone": "壮阔",
        "time_setting": "2187年",
        "location": "地球-太空港"
      },
      "llm_generated": false,
      "children": [
        {
          "id": "770e8400-e29b-41d4-a716-446655440011",
          "node_type": "CHAPTER",
          "title": "第一章：最后的日落",
          "summary": "主角在地球上度过的最后一天",
          "sort_order": 0,
          "metadata": null,
          "llm_generated": true,
          "children": []
        }
      ]
    }
  ]
}
```

### 3.3 创建大纲

```
POST /api/v1/projects/{project_id}/outlines
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| title | string | 是 | 大纲标题，最大 300 字符 |
| description | string | 否 | 大纲描述 |

> `project_id` 从路径参数自动获取，无需在请求体中传递。

### 3.4 AI 生成大纲

```
POST /api/v1/projects/{project_id}/outlines/generate
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| llm_config_id | string (UUID) | 是 | LLM 配置 ID |
| params | object | 是 | 生成参数 |

**params 对象**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| genre | string | 是 | 小说体裁 |
| theme | string | 是 | 主题 |
| style | string | 否 | 写作风格 |
| word_count_target | string | 否 | 目标字数 |
| extra_requirements | string | 否 | 额外要求 |

**请求示例**：

```json
{
  "llm_config_id": "990e8400-e29b-41d4-a716-446655440099",
  "params": {
    "genre": "科幻",
    "theme": "人类在星际间寻找家园",
    "style": "硬科幻，叙事沉稳",
    "word_count_target": "300000",
    "extra_requirements": "三卷本结构，每卷约10万字"
  }
}
```

**响应示例**（201 Created）：

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "星际迷途大纲",
  "description": "三卷本结构：启航、迷失、归途",
  "version": 1,
  "created_at": "2026-05-29T10:00:00Z",
  "updated_at": "2026-05-29T10:00:00Z"
}
```

### 3.5 AI 扩展大纲节点

```
POST /api/v1/projects/{project_id}/outlines/nodes/{node_id}/expand
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| llm_config_id | string (UUID) | 是 | LLM 配置 ID |
| params | object | 否 | 扩展参数 |

**params 对象**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| count | integer | 否 | 生成子节点数量，默认 3 |
| siblings_info | string | 否 | 兄弟节点信息 |
| request | string | 否 | 扩展要求描述 |

**响应示例**（201 Created）：

```json
{
  "data": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440020",
      "outline_id": "660e8400-e29b-41d4-a716-446655440001",
      "parent_id": "770e8400-e29b-41d4-a716-446655440010",
      "node_type": "SCENE",
      "title": "告别仪式",
      "summary": "太空港的告别仪式，主角与家人道别",
      "sort_order": 0,
      "metadata": { "emotional_tone": "感伤" },
      "llm_generated": true,
      "created_at": "2026-05-29T11:00:00Z",
      "updated_at": "2026-05-29T11:00:00Z"
    }
  ]
}
```

### 3.6 AI 优化大纲

```
POST /api/v1/projects/{project_id}/outlines/{outline_id}/optimize
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| llm_config_id | string (UUID) | 是 | LLM 配置 ID |
| direction | string | 否 | 优化方向描述 |

**响应示例**：

```json
{
  "issues": [
    {
      "location": "第二卷第三章",
      "description": "情节转折过于突兀，缺少铺垫",
      "severity": "medium"
    }
  ],
  "suggestions": [
    {
      "target": "第二卷第二章",
      "action": "增加伏笔段落，暗示后续转折",
      "reason": "为第三章的转折提供逻辑支撑"
    }
  ],
  "optimized_structure": { ... }
}
```

### 3.7 添加大纲节点

```
POST /api/v1/projects/{project_id}/outlines/nodes
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| outline_id | string (UUID) | 是 | 大纲 ID |
| parent_id | string (UUID) \| null | 否 | 父节点 ID，null 表示根节点 |
| node_type | string | 是 | 节点类型：VOLUME / CHAPTER / SCENE / PLOT_POINT / KEY_EVENT |
| title | string | 是 | 标题 |
| summary | string | 否 | 概述 |
| sort_order | integer | 否 | 排序序号，默认 0 |
| metadata | object | 否 | 元数据 |

### 3.8 更新大纲节点

```
PUT /api/v1/projects/{project_id}/outlines/nodes/{node_id}
```

**请求体**：同添加节点，所有字段可选。

### 3.9 移动大纲节点

```
PUT /api/v1/projects/{project_id}/outlines/nodes/{node_id}/move
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| new_parent_id | string (UUID) \| null | 是 | 新父节点 ID |
| new_order | integer | 是 | 新排序位置 |

### 3.10 删除大纲节点

```
DELETE /api/v1/projects/{project_id}/outlines/nodes/{node_id}
```

**响应**：204 No Content。级联删除所有子节点。

---

## 4. 人物管理接口

> 所有人物接口均嵌套在项目路径下，`project_id` 为路径参数，自动校验项目存在性。

### 4.1 获取人物列表

```
GET /api/v1/projects/{project_id}/characters
```

**响应示例**：

```json
{
  "data": [
    {
      "id": "880e8400-e29b-41d4-a716-446655440030",
      "project_id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "林远",
      "aliases": ["舰长", "老林"],
      "avatar_url": null,
      "basic_info": {
        "age": "35",
        "gender": "男",
        "occupation": "星际飞船舰长",
        "appearance": "身材高大，目光坚毅，左颊有一道细长疤痕",
        "background": "前地球联合舰队最年轻的舰长，因一次事故主动降级"
      },
      "personality": {
        "traits": ["果断", "沉稳", "内心孤独", "责任感强"],
        "mbti": "INTJ",
        "values": ["责任", "真相", "生存"],
        "flaws": ["过于自我牺牲", "难以信任他人"],
        "speaking_style": "简洁有力，少用修辞，关键时刻才展露情感"
      },
      "growth_arc": {
        "starting_state": "因过去的失败而封闭自我，只依靠自己",
        "catalyst": "被迫与一群陌生人共同求生",
        "transformation": "逐渐学会信任和依赖同伴",
        "ending_state": "成为真正的领袖，不再独自承担一切"
      },
      "notes": "核心主角，所有情节围绕其成长展开",
      "created_at": "2026-05-29T10:00:00Z",
      "updated_at": "2026-05-29T12:00:00Z"
    }
  ]
}
```

### 4.2 获取人物详情

```
GET /api/v1/projects/{project_id}/characters/{character_id}
```

### 4.3 创建人物

```
POST /api/v1/projects/{project_id}/characters
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| name | string | 是 | 人物名称，最大 100 字符 |
| aliases | string[] | 否 | 别名列表 |
| avatar_url | string | 否 | 头像 URL |
| basic_info | object | 否 | 基本信息 |
| personality | object | 否 | 性格特征 |
| growth_arc | object | 否 | 成长弧线 |
| notes | string | 否 | 备注 |

> `project_id` 从路径参数自动获取，无需在请求体中传递。

**basic_info 对象**：

| 字段 | 类型 | 描述 |
|------|------|------|
| age | string | 年龄 |
| gender | string | 性别 |
| occupation | string | 职业 |
| appearance | string | 外貌描述 |
| background | string | 背景故事 |

**personality 对象**：

| 字段 | 类型 | 描述 |
|------|------|------|
| traits | string[] | 性格特征列表 |
| mbti | string | MBTI 类型 |
| values | string[] | 价值观列表 |
| flaws | string[] | 缺陷列表 |
| speaking_style | string | 说话风格 |

**growth_arc 对象**：

| 字段 | 类型 | 描述 |
|------|------|------|
| starting_state | string | 初始状态 |
| catalyst | string | 转变催化剂 |
| transformation | string | 转变过程 |
| ending_state | string | 最终状态 |

### 4.4 更新人物

```
PUT /api/v1/projects/{project_id}/characters/{character_id}
```

**请求体**：同创建人物，所有字段可选。

### 4.5 删除人物

```
DELETE /api/v1/projects/{project_id}/characters/{character_id}
```

### 4.6 AI 生成人物档案

```
POST /api/v1/projects/{project_id}/characters/generate
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| llm_config_id | string (UUID) | 是 | LLM 配置 ID |
| description | string | 是 | 人物描述（自然语言） |

**请求示例**：

```json
{
  "llm_config_id": "990e8400-e29b-41d4-a716-446655440099",
  "description": "一位35岁的星际飞船舰长，男性，性格果断沉稳但内心孤独，因过去的失败而封闭自我"
}
```

**响应示例**（201 Created）：返回完整的人物档案对象。

### 4.7 AI 一键导入多个人物（从文本）

```
POST /api/v1/projects/{project_id}/characters/import
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| llm_config_id | string (UUID) | 是 | LLM 配置 ID |
| text_content | string | 是 | 包含人物信息的文本（可包含多人） |

**请求示例**：

```json
{
  "llm_config_id": "990e8400-e29b-41d4-a716-446655440099",
  "text_content": "林墨寒，男，28岁，江湖人称'寒剑'。出身江南林家，幼年家族遭灭门之祸，被隐世高人救走并传授剑法。性格外冷内热。\n\n苏婉清，女，24岁，医谷传人。温婉聪慧，医术精湛..."
}
```

**响应示例**（201 Created）：

```json
{
  "data": [
    {
      "id": "880e8400-e29b-41d4-a716-446655440030",
      "project_id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "林墨寒",
      "aliases": ["寒剑"],
      "basic_info": { "年龄": "28", "性别": "男", "职业": "剑客" },
      "personality": { "性格特征": "外冷内热" },
      "growth_arc": null,
      "notes": null,
      "created_at": "2026-06-01T08:00:00",
      "updated_at": "2026-06-01T08:00:00"
    }
  ],
  "count": 1
}
```

> **实现细节**：`character_service.import_from_text` 调用 LLM 用 `CHARACTER_IMPORT_SYSTEM` / `CHARACTER_IMPORT_USER` 提示词（`backend/app/llm/prompts/chapter.py`），要求返回 JSON 数组。系统会先用 `_extract_json` 兼容 ```json 代码块、嵌套引号等边界情况。

### 4.8 获取人物关系列表

```
GET /api/v1/projects/{project_id}/characters/relationships
```

**响应示例**：

```json
{
  "data": [
    {
      "id": "880e8400-e29b-41d4-a716-446655440040",
      "project_id": "550e8400-e29b-41d4-a716-446655440000",
      "source_id": "880e8400-e29b-41d4-a716-446655440030",
      "target_id": "880e8400-e29b-41d4-a716-446655440031",
      "relationship_type": "ALLY",
      "description": "相互信任的战友",
      "intensity": 8,
      "start_chapter": "第3章",
      "end_chapter": null,
      "metadata": null,
      "source_name": "林远",
      "target_name": "苏晴"
    }
  ]
}
```

### 4.9 创建人物关系

```
POST /api/v1/projects/{project_id}/characters/relationships
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| source_id | string (UUID) | 是 | 源人物 ID |
| target_id | string (UUID) | 是 | 目标人物 ID |
| relationship_type | string | 是 | 关系类型：FAMILY / FRIEND / ENEMY / LOVER / MENTOR / SUBORDINATE / ALLY / RIVAL / OTHER |
| description | string | 否 | 关系描述 |
| intensity | integer | 否 | 关系强度 1-10，默认 5 |
| start_chapter | string | 否 | 关系起始章节 |
| end_chapter | string | 否 | 关系结束章节 |

> `project_id` 从路径参数自动获取。

### 4.10 更新人物关系

```
PUT /api/v1/projects/{project_id}/characters/relationships/{relationship_id}
```

### 4.11 删除人物关系

```
DELETE /api/v1/projects/{project_id}/characters/relationships/{relationship_id}
```

---

## 5. 章节管理接口

> 所有章节接口均嵌套在项目路径下，`project_id` 为路径参数，自动校验项目存在性。

### 5.1 获取章节列表

```
GET /api/v1/projects/{project_id}/chapters
```

**响应示例**：

```json
{
  "data": [
    {
      "id": "a80e8400-e29b-41d4-a716-446655440050",
      "project_id": "550e8400-e29b-41d4-a716-446655440000",
      "outline_node_id": "770e8400-e29b-41d4-a716-446655440011",
      "title": "第一章：最后的日落",
      "content": "<p>夕阳将最后一缕金光洒在...</p>",
      "summary": "主角在地球上度过的最后一天",
      "sort_order": 0,
      "status": "completed",
      "word_count": 5230,
      "created_at": "2026-05-29T10:00:00Z",
      "updated_at": "2026-05-29T16:00:00Z"
    }
  ]
}
```

### 5.2 获取章节详情

```
GET /api/v1/projects/{project_id}/chapters/{chapter_id}
```

### 5.3 创建章节

```
POST /api/v1/projects/{project_id}/chapters
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| outline_node_id | string (UUID) | 否 | 关联的大纲节点 ID |
| title | string | 是 | 章节标题 |
| content | string | 否 | 章节内容（HTML） |
| sort_order | integer | 否 | 排序序号 |

> `project_id` 从路径参数自动获取。

### 5.4 更新章节

```
PUT /api/v1/projects/{project_id}/chapters/{chapter_id}
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| title | string | 否 | 章节标题 |
| content | string | 否 | 章节内容（HTML） |
| summary | string | 否 | 章节摘要 |
| status | string | 否 | 状态：draft / in_progress / completed / revised |
| word_count | integer | 否 | 字数 |

### 5.5 删除章节

```
DELETE /api/v1/projects/{project_id}/chapters/{chapter_id}
```

### 5.6 AI 辅助写作

```
POST /api/v1/projects/{project_id}/chapters/{chapter_id}/ai-assist
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| llm_config_id | string (UUID) | 是 | LLM 配置 ID |
| action | string | 是 | 操作类型：continue / rewrite / polish / expand / summarize / dialogue |
| selection | string | 否 | 选中的文本（rewrite/polish 时必填） |
| context | string | 否 | 额外上下文或要求 |

**action 说明**：

| 值 | 描述 | 必填字段 |
|----|------|----------|
| continue | 续写 | - |
| rewrite | 改写 | selection |
| polish | 润色 | selection |
| expand | 扩写 | selection |
| summarize | 生成摘要 | - |
| dialogue | 生成对话 | context（人物信息） |

**响应示例**：

```json
{
  "content": "飞船缓缓驶离太空港，窗外的地球越来越小...",
  "action": "continue",
  "tokens_used": 450
}
```

### 5.7 AI 流式续写

```
POST /api/v1/projects/{project_id}/chapters/{chapter_id}/ai-stream
```

**请求体**：同 AI 辅助写作。

**响应**：SSE (Server-Sent Events) 流

```
event: chunk
data: {"content": "飞船"}

event: chunk
data: {"content": "缓缓"}

event: chunk
data: {"content": "驶离太空港"}

event: done
data: {}
```

### 5.8 整本小说写作（同步）

```
POST /api/v1/projects/{project_id}/chapters/{chapter_id}/novel-write
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| llm_config_id | string (UUID) | 是 | LLM 配置 ID |
| style_requirements | string | 否 | 风格要求（不传则用默认"细腻、紧凑、具有网文阅读感的叙事风格"） |

**请求示例**：

```json
{
  "llm_config_id": "990e8400-e29b-41d4-a716-446655440099",
  "style_requirements": "三幕剧结构，节奏紧凑，每章末尾留悬念"
}
```

**响应示例**：

```json
{
  "content": "夜色如墨，倾泻而下。\n\n林墨寒独坐窗前，指尖摩挲着那枚已经冰凉的玉佩……"
}
```

> **实现细节**（`backend/app/services/chapter_service.py` 的 `novel_write`）：服务会组装以下上下文喂给 LLM：
> 1. 章节关联大纲节点的 `summary`（如有）
> 2. 项目所有人物的 `basic_info` / `personality` / `growth_arc` / `notes`
> 3. 上一章节最后 3000 字内容（如有）
> 4. 用户指定的风格要求
>
> 返回的完整内容**不会自动写回 chapter 表**——调用方拿到结果后用 `PUT /chapters/{id}` 自行保存。如需自动保存，请用流式版本（5.9）。

### 5.9 整本小说写作（流式 SSE，自动保存）

```
POST /api/v1/projects/{project_id}/chapters/{chapter_id}/novel-write-stream
```

**请求体**：同 5.8。

**响应**：SSE 流，**流式输出完成后会自动写回 chapter.content 并按中文字符数更新 word_count**。

```
event: chunk
data: {"content": "夜色"}

event: chunk
data: {"content": "如墨"}

event: done
data: {}
```

> 区别于 5.8：路由在 `chapters.py:160` 直接组装上下文 + 流式输出 + 自动 commit，**省去客户端二次调用 PUT**。适合前端"一键整本写"按钮的实场景。

### 5.10 获取章节版本列表

```
GET /api/v1/projects/{project_id}/chapters/{chapter_id}/versions
```

**响应示例**：

```json
{
  "data": [
    {
      "id": "b80e8400-e29b-41d4-a716-446655440060",
      "chapter_id": "a80e8400-e29b-41d4-a716-446655440050",
      "version_number": 3,
      "word_count": 5230,
      "change_summary": "增加结尾段落",
      "created_at": "2026-05-29T16:00:00Z"
    },
    {
      "id": "b80e8400-e29b-41d4-a716-446655440061",
      "chapter_id": "a80e8400-e29b-41d4-a716-446655440050",
      "version_number": 2,
      "word_count": 4800,
      "change_summary": "修改对话部分",
      "created_at": "2026-05-29T14:00:00Z"
    }
  ]
}
```

### 5.11 创建版本快照

```
POST /api/v1/projects/{project_id}/chapters/{chapter_id}/versions
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| change_summary | string | 否 | 变更说明 |

**响应**（201 Created）：返回版本详情对象。

### 5.12 版本对比

```
GET /api/v1/projects/{project_id}/chapters/{chapter_id}/versions/compare?v1={v1}&v2={v2}
```

**查询参数**：

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| v1 | integer | 是 | 旧版本号 |
| v2 | integer | 是 | 新版本号 |

**响应示例**：

```json
{
  "version1": 2,
  "version2": 3,
  "additions": 15,
  "deletions": 3,
  "unified_diff": [
    "--- ",
    "+++ ",
    "@@ -45,6 +45,18 @@",
    " 他沉默了许久。",
    "+",
    "+ \"我们真的要离开吗？\"苏晴轻声问道。",
    "+",
    "+ 林远望着窗外渐远的蓝色星球，嘴角微微上扬：",
    "+ \"不是离开。是出发。\"",
    "+",
    "+ 控制台上的倒计时归零，引擎发出低沉的轰鸣。",
    " 飞船开始加速。"
  ],
  "html_diff": "<table class=\"diff\">...</table>"
}
```

---

## 6. 一致性分析接口

> 所有分析接口均嵌套在项目路径下，`project_id` 为路径参数，自动校验项目存在性。分析报告从属于项目。

### 6.1 执行一致性分析

```
POST /api/v1/projects/{project_id}/analysis/consistency
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| llm_config_id | string (UUID) | 是 | LLM 配置 ID |
| chapter_id | string (UUID) | 是 | 待分析章节 ID |
| dimensions | string[] | 否 | 分析维度，默认 ["character", "plot", "timeline"] |

> `project_id` 从路径参数自动获取，无需在请求体中传递。

**dimensions 可选值**：

| 值 | 描述 |
|----|------|
| character | 人物行为一致性 |
| plot | 情节连贯性 |
| timeline | 时间线一致性 |
| setting | 设定一致性 |
| logic | 逻辑合理性 |

**请求示例**：

```json
{
  "llm_config_id": "990e8400-e29b-41d4-a716-446655440099",
  "chapter_id": "a80e8400-e29b-41d4-a716-446655440050",
  "dimensions": ["character", "plot"]
}
```

**响应示例**：

```json
{
  "character": {
    "issues": [
      {
        "type": "character_inconsistency",
        "character_name": "林远",
        "location": "第3段",
        "description": "林远在此处表现出轻率的言行，与其'沉稳'的性格设定矛盾",
        "severity": "medium",
        "suggestion": "将'他毫不犹豫地冲了上去'改为'他快速权衡后做出了决定'"
      }
    ],
    "score": 82
  },
  "plot": {
    "issues": [
      {
        "type": "plot_inconsistency",
        "location": "第7段",
        "description": "此处提到飞船已进入超光速，但前文设定该飞船不具备超光速引擎",
        "severity": "high",
        "suggestion": "修改为'亚光速巡航'或在前文补充超光速引擎的设定"
      }
    ],
    "score": 75
  }
}
```

### 6.2 流式一致性分析

```
POST /api/v1/projects/{project_id}/analysis/consistency/stream
```

**请求体**：同一致性分析，但 `dimensions` 只支持单个维度。

**响应**：SSE 流，逐步输出分析结果。

### 6.3 获取分析报告列表

```
GET /api/v1/projects/{project_id}/analysis/reports
```

**查询参数**：

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| chapter_id | string (UUID) | 否 | 按章节筛选 |
| analysis_type | string | 否 | 按分析类型筛选 |

### 6.4 获取分析报告详情

```
GET /api/v1/projects/{project_id}/analysis/reports/{report_id}
```

**响应示例**：

```json
{
  "id": "c80e8400-e29b-41d4-a716-446655440070",
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "chapter_id": "a80e8400-e29b-41d4-a716-446655440050",
  "analysis_type": "character",
  "status": "completed",
  "issues": [
    {
      "type": "character_inconsistency",
      "character_name": "林远",
      "location": "第3段",
      "description": "言行与性格设定矛盾",
      "severity": "medium",
      "suggestion": "调整表述以符合沉稳性格"
    }
  ],
  "suggestions": [
    {
      "target": "第3段第2句",
      "action": "修改措辞",
      "reason": "保持人物性格一致性"
    }
  ],
  "score": 82.0,
  "created_at": "2026-05-29T17:00:00Z",
  "updated_at": "2026-05-29T17:00:00Z"
}
```

---

## 7. 导出接口

> 导出接口嵌套在项目路径下，`project_id` 为路径参数。

### 7.1 导出项目

```
POST /api/v1/projects/{project_id}/export
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| format | string | 是 | 导出格式：txt / markdown / docx |
| options | object | 否 | 导出选项 |

> `project_id` 从路径参数自动获取，无需在请求体中传递。

**options 对象**：

| 字段 | 类型 | 描述 |
|------|------|------|
| include_outline | boolean | 是否包含大纲，默认 false |
| include_characters | boolean | 是否包含人物档案，默认 false |
| include_metadata | boolean | 是否包含元数据，默认 true |
| chapter_range | object | 导出章节范围 { start: int, end: int } |

**请求示例**：

```json
{
  "format": "markdown",
  "options": {
    "include_outline": true,
    "include_characters": true,
    "chapter_range": { "start": 1, "end": 10 }
  }
}
```

**响应**：二进制文件流

| 格式 | Content-Type | 文件扩展名 |
|------|-------------|-----------|
| txt | text/plain; charset=utf-8 | .txt |
| markdown | text/markdown; charset=utf-8 | .md |
| docx | application/vnd.openxmlformats-officedocument.wordprocessingml.document | .docx |

**响应头**：

```
Content-Disposition: attachment; filename="星际迷途.md"
Content-Type: text/markdown; charset=utf-8
```

---

## 8. LLM 配置接口

> LLM 配置为全局资源，不绑定特定项目，路径独立于项目。

### 8.1 获取配置列表

```
GET /api/v1/llm-configs
```

**响应示例**：

```json
{
  "data": [
    {
      "id": "990e8400-e29b-41d4-a716-446655440099",
      "provider": "deepseek",
      "api_key_encrypted": "****masked****",
      "base_url": "https://api.deepseek.com",
      "model_name": "deepseek-v4-pro",
      "default_params": {
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 4096,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0
      },
      "rate_limit": {
        "requests_per_minute": 30,
        "max_concurrent": 3
      },
      "is_active": true,
      "created_at": "2026-05-29T09:00:00Z",
      "updated_at": "2026-05-29T09:00:00Z"
    }
  ]
}
```

> **注意**：`api_key_encrypted` 字段在列表和详情接口中始终返回脱敏值 `****masked****`，不会暴露加密后的密钥。

### 8.2 获取配置详情

```
GET /api/v1/llm-configs/{config_id}
```

### 8.3 创建配置

```
POST /api/v1/llm-configs
```

**请求体**：

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| provider | string | 是 | 服务商：deepseek / openai_compatible |
| api_key | string | 是 | API 密钥（明文，服务端加密存储） |
| base_url | string | 是 | API 基础地址 |
| model_name | string | 是 | 模型名称 |
| default_params | object | 否 | 默认参数 |
| rate_limit | object | 否 | 频率限制 |

**default_params 对象**：

| 字段 | 类型 | 范围 | 默认值 | 描述 |
|------|------|------|--------|------|
| temperature | float | 0.0-2.0 | 0.7 | 生成温度 |
| top_p | float | 0.0-1.0 | 0.9 | Top-P 采样 |
| max_tokens | integer | 1-65536 | 4096 | 最大输出 Token |
| frequency_penalty | float | -2.0-2.0 | 0.0 | 频率惩罚 |
| presence_penalty | float | -2.0-2.0 | 0.0 | 存在惩罚 |

**rate_limit 对象**：

| 字段 | 类型 | 描述 |
|------|------|------|
| requests_per_minute | integer | 每分钟最大请求数 |
| tokens_per_minute | integer | 每分钟最大 Token 数 |
| max_concurrent | integer | 最大并发请求数 |

**请求示例**：

```json
{
  "provider": "deepseek",
  "api_key": "YOUR_API_KEY",
  "base_url": "https://api.deepseek.com",
  "model_name": "deepseek-v4-pro",
  "default_params": {
    "temperature": 0.7,
    "top_p": 0.9,
    "max_tokens": 4096
  },
  "rate_limit": {
    "requests_per_minute": 30,
    "max_concurrent": 3
  }
}
```

### 8.4 更新配置

```
PUT /api/v1/llm-configs/{config_id}
```

**请求体**：同创建配置，所有字段可选。`api_key` 若不传则保持原值不变。

### 8.5 删除配置

```
DELETE /api/v1/llm-configs/{config_id}
```

### 8.6 测试连接

```
POST /api/v1/llm-configs/{config_id}/test
```

**响应示例**：

```json
{
  "success": true,
  "message": "连接成功",
  "model_info": {
    "model_name": "deepseek-v4-pro",
    "latency_ms": 320
  }
}
```

**失败响应示例**：

```json
{
  "success": false,
  "message": "认证失败：无效的 API 密钥",
  "model_info": null
}
```

---

## 9. SSE 事件规范

### 9.1 事件格式

所有 SSE 流式接口遵循以下格式：

```
event: {event_type}
data: {json_payload}

```

### 9.2 事件类型

| 事件类型 | 描述 | payload |
|----------|------|---------|
| chunk | 内容片段 | `{"content": "..."}` |
| thinking | 思考过程（如模型支持） | `{"content": "..."}` |
| usage | Token 用量 | `{"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}` |
| done | 流式输出完成 | `{}` |
| error | 错误 | `{"code": "LLM_REQUEST_FAILED", "message": "..."}` |

### 9.3 完整 SSE 流示例

```
event: chunk
data: {"content": "飞船"}

event: chunk
data: {"content": "缓缓"}

event: chunk
data: {"content": "驶离太空港"}

event: usage
data: {"prompt_tokens": 256, "completion_tokens": 45, "total_tokens": 301}

event: done
data: {}
```

---

## 10. 数据校验规则

### 10.1 通用规则

| 规则 | 描述 |
|------|------|
| UUID 格式 | 所有 ID 字段必须符合 UUID v4 格式 |
| 字符串长度 | 按各字段定义的最大长度校验 |
| 枚举值 | node_type、relationship_type、status 等字段必须为预定义枚举值 |
| JSON 字段 | metadata、basic_info 等字段必须为合法 JSON |
| 项目归属 | 所有项目级接口自动校验资源 `project_id` 与路径参数一致 |

### 10.2 业务规则

| 规则 | 描述 |
|------|------|
| 项目唯一性 | 同一项目名称不重复（软约束，可覆盖） |
| 大纲节点层级 | 最大支持 5 层嵌套（VOLUME → CHAPTER → SCENE → PLOT_POINT → KEY_EVENT） |
| 人物关系对称 | 创建关系时自动检查反向关系是否已存在 |
| 章节排序 | sort_order 在同一项目内唯一且连续 |
| LLM 配置 | 同一 provider + base_url + model_name 组合唯一 |
| API 密钥 | 创建/更新时加密存储，读取时脱敏返回 |
| 项目级资源隔离 | 所有项目级 API 的 `project_id` 从路径参数获取，服务端校验资源归属 |

---

## 11. 接口调用示例

### 11.1 完整创作流程

```bash
# 1. 创建 LLM 配置（全局资源）
curl -X POST http://localhost:8000/api/v1/llm-configs \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "deepseek",
    "api_key": "YOUR_API_KEY",
    "base_url": "https://api.deepseek.com",
    "model_name": "deepseek-v4-pro",
    "default_params": {"temperature": 0.7, "top_p": 0.9, "max_tokens": 4096},
    "rate_limit": {"requests_per_minute": 30, "max_concurrent": 3}
  }'

# 2. 创建项目
curl -X POST http://localhost:8000/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"name": "星际迷途", "genre": "科幻", "word_count_target": 300000}'

# 3. AI 生成大纲（嵌套在项目下）
curl -X POST http://localhost:8000/api/v1/projects/<project_id>/outlines/generate \
  -H "Content-Type: application/json" \
  -d '{
    "llm_config_id": "<config_id>",
    "params": {"genre": "科幻", "theme": "星际探索", "style": "硬科幻"}
  }'

# 4. 创建人物（嵌套在项目下）
curl -X POST http://localhost:8000/api/v1/projects/<project_id>/characters \
  -H "Content-Type: application/json" \
  -d '{"name": "林远", "basic_info": {"age": "35", "gender": "男"}}'

# 5. 创建章节（嵌套在项目下）
curl -X POST http://localhost:8000/api/v1/projects/<project_id>/chapters \
  -H "Content-Type: application/json" \
  -d '{"title": "第一章：最后的日落", "sort_order": 0}'

# 6. AI 续写（嵌套在项目下）
curl -X POST http://localhost:8000/api/v1/projects/<project_id>/chapters/<chapter_id>/ai-assist \
  -H "Content-Type: application/json" \
  -d '{"llm_config_id": "<config_id>", "action": "continue"}'

# 7. 一致性分析（嵌套在项目下）
curl -X POST http://localhost:8000/api/v1/projects/<project_id>/analysis/consistency \
  -H "Content-Type: application/json" \
  -d '{
    "llm_config_id": "<config_id>",
    "chapter_id": "<chapter_id>",
    "dimensions": ["character", "plot"]
  }'

# 8. 导出项目（嵌套在项目下）
curl -X POST http://localhost:8000/api/v1/projects/<project_id>/export \
  -H "Content-Type: application/json" \
  -d '{"format": "markdown"}' \
  -o output.md
```

---

## 12. 新旧接口路径对照

| 旧路径 | 新路径 | 变化说明 |
|--------|--------|----------|
| `GET /api/v1/outlines?project_id=xxx` | `GET /api/v1/projects/{pid}/outlines` | project_id 从查询参数变为路径参数 |
| `POST /api/v1/outlines` | `POST /api/v1/projects/{pid}/outlines` | 嵌套到项目路径下 |
| `POST /api/v1/outlines/generate` | `POST /api/v1/projects/{pid}/outlines/generate` | 嵌套到项目路径下 |
| `GET /api/v1/characters?project_id=xxx` | `GET /api/v1/projects/{pid}/characters` | project_id 从查询参数变为路径参数 |
| `POST /api/v1/characters` | `POST /api/v1/projects/{pid}/characters` | 嵌套到项目路径下 |
| `POST /api/v1/characters/generate` | `POST /api/v1/projects/{pid}/characters/generate` | 嵌套到项目路径下 |
| `GET /api/v1/characters/relationships?project_id=xxx` | `GET /api/v1/projects/{pid}/characters/relationships` | project_id 从查询参数变为路径参数 |
| `GET /api/v1/chapters?project_id=xxx` | `GET /api/v1/projects/{pid}/chapters` | project_id 从查询参数变为路径参数 |
| `POST /api/v1/chapters` | `POST /api/v1/projects/{pid}/chapters` | 嵌套到项目路径下 |
| `POST /api/v1/analysis/consistency` | `POST /api/v1/projects/{pid}/analysis/consistency` | 嵌套到项目路径下，project_id 从请求体移到路径 |
| `GET /api/v1/analysis/reports?project_id=xxx` | `GET /api/v1/projects/{pid}/analysis/reports` | project_id 从查询参数变为路径参数 |
| `POST /api/v1/export` | `POST /api/v1/projects/{pid}/export` | project_id 从请求体移到路径 |
| `GET /api/v1/llm-configs` | `GET /api/v1/llm-configs` | 无变化，全局资源 |
