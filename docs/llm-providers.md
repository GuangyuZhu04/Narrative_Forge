# LLM Provider 适配说明

> 更新于 2026-08-13。模型和服务端能力会持续变化；模型名允许在配置页手动填写，但 API 表面与结构化输出能力由后端适配器明确控制。

## Provider 与 API 表面

| provider | 默认 Base URL | API 表面 | 说明 |
| --- | --- | --- | --- |
| `deepseek` | `https://api.deepseek.com` | Chat Completions 或 Responses | `deepseek-v4-flash` 与 `deepseek-v4-pro` 在未指定 `api_mode` 时默认使用 `/responses` |
| `openai` | `https://api.openai.com/v1` | Responses | 支持 Responses 消息项、工具调用、结构化输出和 `prompt_cache_key` |
| `anthropic` | `https://api.anthropic.com/v1` | Messages | `system` 与 `messages[]`，结构化输出映射到 `output_config.format` |
| `google` | `https://generativelanguage.googleapis.com/v1beta` | `generateContent` | API Key 通过 `x-goog-api-key` 请求头发送，不写入 URL |
| `openai_compatible` | 自定义 | Chat Completions | 保守地只调用 `/chat/completions`，不会因为模型名自动切到 Responses |

DeepSeek 的 `api_mode`/`interface` 显式设置优先于自动判断：

- `api_mode: "chat_completions"`：强制 Chat Completions；控制参数不会下发到上游请求体。
- `api_mode: "responses"`：强制 Responses；当前支持 `deepseek-v4-flash` 与 `deepseek-v4-pro`，其他模型会在发请求前报配置错误。
- 未设置：上述两个 DeepSeek V4 模型默认使用 Responses，其他模型使用 Chat Completions。
- `use_responses_api: true/false` 作为兼容控制项保留；推荐新配置使用 `api_mode`。

DeepSeek Responses 当前没有服务端会话状态。每一轮必须在 `input` 中带上完整历史；不要依赖 `previous_response_id`、`conversation` 或 `store`。这些字段不受支持且可能被服务端静默忽略。后端会保留并允许回传以下语义项：

- `message`
- `reasoning`
- `function_call`
- `function_call_output`
- `web_search_call`

## 统一返回契约

`app.llm.contracts` 提供 Provider 无关的类型：

- `LLMResult.text`：兼容现有业务的纯文本。
- `LLMResult.output_items`：未经文本扁平化的语义输出项。
- `LLMResult.tool_calls`：统一后的函数调用 ID、名称与 JSON 参数。
- `LLMResult.finish_status`：`completed`、`incomplete`、`failed`、`cancelled`、`tool_calls` 或 `unknown`。
- `LLMResult.usage`：输入、输出、总量、缓存命中输入和推理 token。
- `response_id`、`model`：用于追踪与用量归因，不作为 DeepSeek 会话状态使用。

业务代码可调用：

```python
result = await llm_orchestrator.response(config_id, messages, **params)
```

原有的 `llm_orchestrator.chat(...) -> str` 保持兼容，内部返回 `result.text`。流式调用可使用 `stream_chat_events`；除 `content`、`thinking` 外，还可能收到：

- `tool_call_delta`：函数参数增量。
- `output_item`：完成的 Responses 语义项。
- `usage`：终态、模型、响应 ID 以及 token/cache 用量。

只消费正文的旧代码可以继续使用 `stream_chat`。

## 消息与工具格式

普通对话继续使用：

```json
[
  {"role": "system", "content": "稳定的系统提示词"},
  {"role": "user", "content": "用户输入"},
  {"role": "assistant", "content": "上一轮回复"}
]
```

Responses 适配器把普通 `system`/`developer` 内容合并到 `instructions`，把其他普通消息写入 `input`。已经是 Responses 语义项的历史不会被转成字符串。工具定义既接受 Chat 格式：

```json
{"type":"function","function":{"name":"save_outline","parameters":{"type":"object"}}}
```

也接受 Responses 格式：

```json
{"type":"function","name":"save_outline","parameters":{"type":"object"}}
```

适配器会按上游 API 表面转换，避免业务层维护多套工具定义。

## 结构化输出映射

业务层可继续传 `response_format`，也可直接传 `json_schema` 与可选的 `schema_name`：

```python
await llm_orchestrator.response(
    config_id,
    messages,
    json_schema={
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
        "additionalProperties": False,
    },
    schema_name="novel_outline",
)
```

映射规则：

| Provider/API | 上游字段 |
| --- | --- |
| DeepSeek Responses | `text.format`；可移植 JSON Schema 降级为 `json_object`，必需字段和业务结构由本地校验 |
| OpenAI Responses | `text.format` |
| DeepSeek/OpenAI-compatible Chat | `response_format` |
| Anthropic Messages | `output_config.format` |
| Google Gemini | `generationConfig.responseMimeType = "application/json"`，JSON Schema 写入 `responseJsonSchema` |

`max_tokens` 会分别映射为 Responses 的 `max_output_tokens`、Anthropic 的 `max_tokens`、Gemini 的 `maxOutputTokens`。DeepSeek 会先合并 `max_tokens`、`max_completion_tokens`、`max_output_tokens` 三种别名，再规范为当前接口的唯一字段；本次调用显式传入的任一别名优先于 LLM 配置中的默认别名。Agent 生成、对话创作和续写改编都会先按模型解析有效预算，DeepSeek V4 使用官方最大 384K。OpenAI 的 `prompt_cache_key` 会原样透传。

DeepSeek 普通 JSON Output 官方只保证 `json_object`。为了避免 `/responses` 在推理前拒绝 `maxLength`、`maxItems` 等严格 Schema 关键字，适配器会把 `json_schema` 降级为 `json_object`；原 Schema 中适用于当前业务的必需字段和结构约束仍由提示词及本地 normalizer/validator 执行，不把供应商兼容性当作本地数据校验的替代品。

## 流终态与错误

OpenAI/DeepSeek Responses 流必须出现 `response.completed`、`response.incomplete`、`response.failed` 或 `response.cancelled` 终态。仅收到正文增量后连接中断会抛出流协议错误，不会把半章内容当作成功结果保存。

- `max_output_tokens`/`max_tokens`：抛出 `LLMOutputTruncatedError`。
- `content_filter`/`safety`/取消：抛出 `LLMContentFilteredError`。
- `failed`：保留上游失败语义并抛出异常。

配置连通性测试会清理 HTTP URL、Authorization 和 API Key 信息；Gemini Key 不会出现在异常 URL 中。

## 配置缓存与限流

Orchestrator 对每个 `llm_config_id` 分别维护 provider 和令牌桶，配置之间不会共享 RPM 状态。每次调用都会比较持久化配置指纹；模型、Base URL、默认参数、限流或加密 Key 发生变化时自动重建 provider。停用配置会在请求上游前拒绝，更新和删除 API 也会立即使本地缓存失效。

为了提高服务端前缀缓存命中率，建议消息顺序保持为：稳定系统提示词 → 稳定且规范化的项目快照 → 完整历史 → 最新用户输入。不要在稳定前缀中加入时间戳或随机值。创作正文不建议做应用层结果缓存；应优先观察 `usage.cached_input_tokens`。

## 官方文档

- [DeepSeek Responses API](https://api-docs.deepseek.com/zh-cn/guides/responses_api)
- [DeepSeek 模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing)
- [DeepSeek上下文缓存](https://api-docs.deepseek.com/guides/kv_cache)
- [OpenAI Responses API](https://developers.openai.com/api/reference/responses/overview)
- [Anthropic Messages API](https://docs.anthropic.com/en/api/messages)
- [Anthropic Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Google generateContent API](https://ai.google.dev/api/generate-content)
