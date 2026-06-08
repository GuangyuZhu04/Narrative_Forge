# LLM Provider 支持

> 截至 2026-06-08 按各服务商官方文档整理。模型名更新很快，前端会提供推荐模型，但仍允许手动输入新模型名。

## Provider 一览

| provider | 默认 Base URL | 推荐模型 | 后端消息格式 |
| --- | --- | --- | --- |
| `deepseek` | `https://api.deepseek.com` | `deepseek-v4-pro` | OpenAI Chat Completions：`messages[]` |
| `openai` | `https://api.openai.com/v1` | `gpt-5.5` | Responses API：`instructions` + `input[]` |
| `anthropic` | `https://api.anthropic.com/v1` | `claude-sonnet-4-6` / `claude-opus-4-8` / `claude-haiku-4-5` | Messages API：`system` + `messages[]` |
| `google` | `https://generativelanguage.googleapis.com/v1beta` | `gemini-3.5-flash` / `gemini-3.1-pro` | Gemini API：`systemInstruction` + `contents[]` |
| `openai_compatible` | 自定义 | 由兼容服务决定 | OpenAI Chat Completions：`messages[]` |

## 消息格式映射

项目内部统一使用：

```json
[
  {"role": "system", "content": "系统提示词"},
  {"role": "user", "content": "用户输入"},
  {"role": "assistant", "content": "上一轮回复"}
]
```

各 Provider 会在后端转换为服务商格式：

- OpenAI：`system` / `developer` 合并为 Responses API 的 `instructions`，`user` / `assistant` 转为 `input[]`。
- Anthropic：`system` / `developer` 合并为顶层 `system`，`user` / `assistant` 转为 Messages API 的 `messages[]`。
- Google Gemini：`system` / `developer` 合并为 `systemInstruction.parts[]`，`user` 转为 `contents[].role = "user"`，`assistant` 转为 `contents[].role = "model"`。
- DeepSeek / OpenAI Compatible：保持 Chat Completions 的 `messages[]` 格式。

## 参数映射

- `max_tokens` 会映射为 OpenAI 的 `max_output_tokens`、Anthropic 的 `max_tokens`、Google 的 `generationConfig.maxOutputTokens`。
- `temperature` / `top_p` 会尽量透传到对应服务商参数。Google 会转为 `generationConfig.temperature` / `generationConfig.topP`。
- Anthropic 支持 `top_k`；DeepSeek、OpenAI、Google 默认不强制传 `top_k`。
- Google 的 `safetySettings` / `safety_settings` 会转为请求体顶层 `safetySettings`。

## 官方文档

- OpenAI latest model guide: <https://developers.openai.com/api/docs/guides/latest-model>
- OpenAI Responses API: <https://developers.openai.com/api/reference/responses/overview>
- Anthropic models: <https://docs.anthropic.com/en/docs/about-claude/models/overview>
- Anthropic Messages API: <https://docs.anthropic.com/en/api/messages>
- Google Gemini models: <https://ai.google.dev/gemini-api/docs/models>
- Google generateContent API: <https://ai.google.dev/api/generate-content>
