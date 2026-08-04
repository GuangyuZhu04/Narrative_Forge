# 有声书生成

有声书模块会把章节富文本转换为朗读文本，识别引号中的人物对白，按人物声音切分 TTS 请求，并生成单章及合并后的 MP3。任务范围支持全书、大纲中的卷、单个章节。

## AI 自动接入语音 API

在「有声书 → TTS 服务」中可以直接粘贴语音服务的 API 文档：

1. 选择系统设置中已有的文本 LLM 配置。
2. 粘贴包含请求地址、鉴权、请求参数、响应示例、模型和音色说明的文档。
3. 点击「AI 解析并填充设置」。
4. 检查自动生成的设置和警告，单独粘贴语音 API Key。
5. 保存后先试听旁白，再生成单章。

语音 API Key 字段不会发送给用于解析文档的 LLM。粘贴文档中的常见 `Authorization`、`API Key` 和 Token 示例也会在提交给 LLM 前自动遮蔽。AI 生成的请求映射始终可编辑。

对于非 OpenAI 格式的接口，系统可生成通用 HTTP 或 WebSocket 请求映射，支持：

- `GET`、`POST`、`PUT`；
- JSON、表单和纯文本字段 multipart；
- 直接返回 MP3；
- JSON 字段返回 Base64 MP3；
- JSON 字段返回 MP3 下载 URL。
- WebSocket 十六进制或 Base64 MP3 分块。

自定义 WebSocket 模式可在「有声书」设置中配置“每分钟最大新连接数（RPM）”。默认值为 20，通常建议设置在 10–20：MiniMax 免费账户建议 10，充值账户建议 20；如果账号已申请更高额度，可在允许的 1–120 范围内按实际额度填写。该配置按项目保存，并覆盖旧请求映射 JSON 中的同名字段。

MiniMax `POST /v1/t2a_async_v2` 使用专用的「MiniMax 异步有声书（多角色）」模式。其他异步轮询、多步任务和必须上传参考音频的接口不能保证自动适配，解析结果会给出警告。

## MiniMax 异步多角色模式

MiniMax 单个异步 T2A 请求只接受一个 `voice_setting.voice_id`。本项目因此把章节作为业务父任务，先由 LLM 生成结构化语音脚本，再把连续同音色文本作为语音子任务：

1. 调用任务指定的 LLM，把章节正文转换为 `segments` JSON，识别旁白与人物对白；
2. 校验 JSON 结构、人物 ID、文本覆盖度和内容长度，再按人物音色映射合并相邻同音色文本；
3. 每个片段分别调用 `POST /v1/t2a_async_v2`，最多同时处理 4 个片段；
4. 以不超过平台查询限制的频率轮询 `/query/t2a_async_query_v2`；
5. 成功后立即通过 `file_id` 检索并下载 WAV/ZIP 结果，避免临时地址过期；
6. 使用 FFmpeg 统一为 32000 Hz、单声道、PCM 16 bit，并做 -16 LUFS 响度标准化；
7. 同音色长段切点插入 200 ms、角色切换插入 400 ms、章末插入 800 ms 静音；
8. 严格按片段索引拼接 WAV，最后只编码一次 128 kbps MP3。

MiniMax 官方的异步 T2A 创建任务文档规定：直接使用 `text` 字段时单次最长 50,000 字符；使用 `text_file_id` 上传文本文件时可小于 1,000,000 字符。当前项目使用前一种 JSON 直传方式，因此「单次请求最大字符数」允许设置为 100–50,000。较大的值会减少同音色长段产生的子任务数，但单个任务处理、失败重试和重新生成的范围也会更大。官方文档见 [创建语音生成任务](https://platform.minimaxi.com/docs/api-reference/speech-t2a-async-create)。

配置示例：

```text
服务类型：MiniMax 异步有声书（多角色）
服务地址：https://api.minimaxi.com/v1
模型：speech-2.8-hd
旁白声音：账号可用的 voice_id
```

「系统设置 → 有声书 → 音频后处理」中的 FFmpeg 开关默认开启，并按项目保存：

- 开启：后端必须能从 `PATH` 找到 `ffmpeg`。Windows 可安装 FFmpeg 后执行 `ffmpeg -version` 验证；Linux 可使用发行版包管理器安装。创建 MiniMax 异步任务前会先检查依赖，缺失时不会提交付费语音任务。
- 关闭：MiniMax 子任务直接输出 MP3，服务端去除后续片段的 ID3 标签后按原始索引拼接，不需要 FFmpeg；该模式不会统一采样率/响度，也不会插入额外的角色切换静音。

每个片段会持久化 `task_id`、`file_id`、请求哈希和本地音频文件。服务意外重启后优先续查已有任务或复用已经下载的片段；只有恢复失败时才新建一次任务。用户修改文本、模型、音色、语速或 FFmpeg 输出模式后，请求哈希会变化，对应片段才会重新生成。

### LLM 语音脚本 JSON

创建有声书任务时必须选择一个启用的 LLM 配置。后台对每章先请求该 LLM，要求返回：

```json
{
  "segments": [
    {"speaker_id": null, "text": "旁白朗读内容"},
    {"speaker_id": "项目人物 ID", "text": "人物对白"}
  ]
}
```

LLM 只能输出项目中存在的人物 ID。后端会拒绝无效 JSON、未知人物、空片段、明显删减或明显扩写的内容，并根据项目人物音色配置补全 `voice_id`，再生成各 TTS 服务所需的最终请求 JSON。通过校验的语音脚本保存在任务的 `speech_scripts` 中；任务重启时只要正文、人物、音色和 LLM 配置未变化，就会复用脚本而不重复调用 LLM。

DeepSeek 官方当前文档标明 V4 模型上下文长度为 1M、最大输出长度为 384K。语音脚本请求因此会覆盖 LLM 配置中较小的默认值，向 DeepSeek 发送 `max_tokens=393216`；其他 LLM 默认至少使用 16384。`max_tokens` 仍受具体模型上下文长度约束。

### MiniMax 音色管理

- 页面加载时以及点击“查询可用音色”时，后端直接调用 MiniMax `POST /v1/get_voice`。
- MiniMax 只会在设计音色成功用于一次正式语音合成后，才通过 `voice_generation` 查询返回它。因此系统会持久化本项目刚设计的音色，并在查询结果中标记为“等待正式调用”，避免刷新后丢失。
- 查询结果中的复刻/设计音色可直接删除；对于查询不到但已占用的历史 ID，可选择类别并手工输入 `voice_id`，后端调用 MiniMax `POST /v1/delete_voice`，成功后立即再次调用 `/v1/get_voice` 刷新列表。
- MiniMax 规定已删除的 `voice_id` 无法再次使用。系统会持久化已删除 ID 并在创建前阻止复用；若远端对历史 ID 返回 duplicate，也会明确提示换用新 ID 或留空自动生成。

## OpenAI 兼容 / 本地 vLLM 服务

服务需要实现 OpenAI 兼容的 `POST {base_url}/audio/speech`：

```json
{
  "model": "tts-1",
  "input": "需要朗读的文本",
  "voice": "alloy",
  "response_format": "mp3",
  "speed": 1.0
}
```

响应体必须是 MP3 字节。云端服务可填写 API Key；无需认证的本地服务留空即可。例如在本项目占用 8000 端口时，可让本地 TTS 服务监听 8001，并填写 `http://127.0.0.1:8001/v1`。并非所有 vLLM 模型都支持语音合成，请确认所部署的模型与服务端实现了 `/audio/speech`。

## ComfyUI 工作流

1. 在 ComfyUI 中搭建并验证 TTS 工作流。
2. 使用“保存（API 格式）”导出 JSON，而不是普通 UI 工作流 JSON。
3. 把文本输入值替换为字符串 `{{text}}`。
4. 建议把音色输入替换为 `{{voice}}`，把输出文件名前缀替换为 `{{filename_prefix}}`。
5. 工作流最终必须输出 MP3 文件。

支持的占位符：

| 占位符 | 值 |
|---|---|
| `{{text}}` | 当前朗读片段，必需 |
| `{{voice}}` | 旁白或人物的声音 ID / 音色名 |
| `{{speed}}` | 页面设置的语速，数值 |
| `{{filename_prefix}}` | 当前任务的唯一输出前缀 |

服务按 ComfyUI 标准接口调用 `/prompt`、`/history/{prompt_id}` 和 `/view`。如果自定义节点只输出 WAV，请在工作流中增加 MP3 编码/保存节点。

## 对白归属规则

系统支持 `“……”`、`「……」`、`『……』` 和英文双引号。它会在对白前后寻找人物姓名、别名以及“说、问、喊、答、道”等归属语句，也支持“人物名：‘对白’”形式。无法可靠识别的对白使用旁白声音，以减少错误配音。

为了得到更稳定的多人物效果，正文应明确写出对白归属，例如：

```text
林远低声说：“我们现在出发。”
“等等我！”苏晴喊道。
```

## 文件与任务

- 生成文件保存在 `backend/data/audiobooks/{project_id}/{job_id}/`，该目录已被 `.gitignore` 排除。
- MiniMax 原始片段缓存位于任务目录下的 `.segments/`，母带处理中间文件位于 `.work/`。
- 每个任务提供一个范围合并 MP3，并保留各章 MP3 供单独下载。
- 取消或删除任务会清理对应的音频文件。
- 任务由当前 API 进程执行。需要生成有声书时，请使用单个 Uvicorn worker；服务重启后，MiniMax 子任务会按已保存状态续传，其他接入模式仍从头恢复。
- 长篇小说会产生较多 TTS 请求及云端费用，建议先用“试听旁白”和单章范围验证声音与工作流。
- 当前版本尚未把 MiniMax 返回的句级字幕重新偏移并合并成章节字幕；输出产物仍为 MP3。

## 主要 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET / PUT | `/api/v1/projects/{pid}/audiobook/config` | 读取或保存 TTS 与声音映射 |
| PATCH | `/api/v1/projects/{pid}/audiobook/config/character-voices` | 单独保存人物音色映射，不修改其他 TTS 配置 |
| POST | `/api/v1/projects/{pid}/audiobook/config/parse-docs` | 使用现有 LLM 解析语音 API 文档 |
| POST | `/api/v1/projects/{pid}/audiobook/preview` | 生成旁白试听片段 |
| POST | `/api/v1/projects/{pid}/audiobook/voices/query` | 查询 MiniMax 账号可用音色 |
| POST | `/api/v1/projects/{pid}/audiobook/voices/design` | 设计 MiniMax 音色并返回试听 |
| POST | `/api/v1/projects/{pid}/audiobook/voices/delete` | 删除 MiniMax 复刻或设计音色 |
| GET | `/api/v1/projects/{pid}/audiobook/scopes` | 获取全书、卷、章节选项 |
| GET / POST | `/api/v1/projects/{pid}/audiobook/jobs` | 查询或创建生成任务；创建时需提供 `llm_config_id` |
| POST | `/api/v1/projects/{pid}/audiobook/jobs/{id}/cancel` | 取消任务 |
| GET | `/api/v1/projects/{pid}/audiobook/jobs/{id}/files/{filename}` | 下载 MP3 |
| DELETE | `/api/v1/projects/{pid}/audiobook/jobs/{id}` | 删除任务及文件 |
