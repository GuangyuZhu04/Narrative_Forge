# Novel Writing Agent — 排错与已知问题

> 本文档收录本项目历史上踩过的坑和典型 bug 复盘，新人遇到问题时先翻这里。

---

## 1. "导入失败，请检查 LLM 配置后重试"（已修复）

**现象**：在「人物」模块点「一键导入」，输入文本点「开始导入」，弹出 toast 报错，但 LLM API 确实已经配置好。

**根因**：

`backend/app/llm/providers/deepseek.py:18` 的初始化代码：

```python
self.default_params = config.get("default_params", {})
```

`dict.get(key, default)` 只在 key **不存在**时才返回 default。当数据库里 `llm_configs.default_params` 字段存在但值是 `None`（前端创建 LLM 配置时没填这个字段，schema 默认 `None`，入库就是 `None`），`get` 直接返回 `None`。

然后 `_build_payload` 第 57 行 `params = {**self.default_params, **kwargs}` 拿 `None` 去解包就崩 `TypeError: 'NoneType' object is not a mapping`。

前端 `CharacterManager.tsx:213` 的 catch 块对所有错误一视同仁：

```typescript
} catch {
  showToast('error', '导入失败，请检查 LLM 配置后重试')
}
```

所以用户看到"配置好 LLM 了"也无济于事——**这根本不是 LLM key 的问题**。

**修复**（4 处，4 个 todo）：

1. `backend/app/llm/providers/deepseek.py:18`
   ```python
   # 旧
   self.default_params = config.get("default_params", {})
   # 新
   self.default_params = config.get("default_params") or {}
   ```
   注释里写明白为什么不能用 `get(..., {})` 兜底。

2. `backend/app/llm/providers/deepseek.py:57` — 防御性兜底
   ```python
   params = {**(self.default_params or {}), **kwargs}
   ```

3. `backend/app/models/llm_config.py:14` — 模型层默认 dict
   ```python
   default_params: Mapped[dict] = mapped_column(JSON, default=dict)
   ```

4. `backend/app/services/llm_orchestrator.py:62` — 存量数据清洗
   ```python
   "default_params": config.default_params or {},
   ```

**修复后行为**：

| 场景 | 修复前 | 修复后 |
|------|--------|--------|
| `default_params=None` + 假 key | 500 (TypeError) | 401（真正的 key 错） |
| `default_params=None` + 真 key | 500 (TypeError) | SUCCESS |
| `default_params` 完整 + 真 key | SUCCESS | SUCCESS |

**教训**：

- Python 里 `dict.get(key, default)` 跟 `or default` 不等价。前者只在 key 缺失时返回 default，后者还兜底 falsy 值（`None`、`""`、`0`、`False`）。**任何用户可输入字段都该用 `or default` 而不是 `get(key, default)`**。
- 前端 catch 块对所有错误吐同一句提示是反模式。**应该把后端的 `error_code` 透传过来**，让前端能区分"key 无效"、"网络错误"、"JSON 解析失败"等。

---

## 2. "unable to open database file"

**现象**：启动后端时报 `sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) unable to open database file`。

**原因**：`DATABASE_URL` 里的路径不存在，或父目录没创建，或没有写权限。

**解决**：

```bash
# 1. 创建目录
mkdir -p data

# 2. 检查 .env 里的 DATABASE_URL
# 开发环境相对路径示例：
DATABASE_URL=sqlite+aiosqlite:///./data/novel_agent.db

# 3. 确认当前用户对 data/ 有写权限
ls -ld data/
```

---

## 3. 前端 404

**现象**：浏览器控制台报 `GET /api/v1/projects 404 (Not Found)`，或前端页面空白。

**诊断**：

1. 后端真的启动了吗？`curl http://localhost:8000/api/v1/projects` 能返回吗？
2. Vite 代理配对了吗？看 `frontend/vite.config.ts`：
   ```typescript
   server: {
     proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } }
   }
   ```
3. 后端 CORS 允许当前 origin 吗？`.env` 的 `CORS_ORIGINS` 应该包含 `http://localhost:5173`。

---

## 4. AI 功能"假成功"——数据库写了但没真正用

**现象**：点 AI 生成后没报错，但生成的内容跟没生成一样 / 重复旧内容。

**原因**：

- 浏览器缓存：硬刷新（Ctrl+Shift+R）
- LLM 返回空字符串：看后端日志，看 `_extract_json` 抛了什么
- `llm_orchestrator._providers` 缓存了旧 provider：改 LLM 配置后**需要重启后端**才能生效（TODO：按 `(config_id, model_name)` 失效缓存）

---

## 5. LLM 返非 JSON

**现象**：后端报 `json.JSONDecodeError` 或 `ValueError: Cannot extract JSON from LLM response`。

**诊断**：

```bash
# 调用 LLM 配置测试端点，确认模型连接是否正常
curl -X POST http://localhost:8000/api/v1/llm-configs/<id>/test
```

**常见原因 & 修法**：

| 原因 | 修法 |
|------|------|
| Prompt 没强制 JSON 输出 | System prompt 加 `你必须只返回合法的 JSON，不要任何解释` |
| Prompt 给了反例 | 删掉 prompt 里所有"不要 JSON"的说法 |
| 模型太弱 | 换更聪明的模型，或调整 temperature（建议 0.6-0.8） |
| 输出超 max_tokens | 把 `max_tokens` 调大（默认 4096） |
| 文本里有未转义引号 | 提示词约束 + 后端正则清洗 |

`_extract_json`（`backend/app/services/character_service.py`）已经兼容以下三种情况：

1. 纯 JSON
2. 包在 ```json ... ``` 代码块里
3. 文本中夹杂 JSON（提取第一个 `[` 或 `{` 开始到配对结束）

但**不兼容**的情况：

- JSON 内有未配对的括号
- 字符串里出现 `}` 导致提前结束
- 模型输出 markdown 表格而不是 JSON

**应对**：在 Prompt 里强制"先输出 ```json 标记，再输出 JSON 内容"。

---

## 6. SECRET_KEY 改了之后 LLM 配置全废

**现象**：改了 `.env` 里的 `SECRET_KEY`，重启后端，所有 AI 功能报 `decrypt failed`。

**根因**：`backend/app/core/security.py` 的 `decrypt_api_key` 用 `SECRET_KEY` 派生解密密钥，**改了之后旧数据全部解不开**。这是个设计缺陷，目前没有"双重主密钥"过渡机制。

**解决**（用户侧）：

1. 在「设置」里把每个 LLM 配置的 API key 重新填一次
2. 或者**回滚 `SECRET_KEY` 到旧值**

**避免**：

- 第一次配 `SECRET_KEY` 时就想清楚（生产用 32 字节随机）
- 备份 `.env` 文件

**长期方案**（TODO）：

加密时存两份密文（用旧 key + 新 key 各加密一次），解密时尝试新 key，失败回退旧 key；下一次写时统一用新 key。这样可以实现平滑轮换。

---

## 7. CORS 跨域错误

**现象**：浏览器控制台：

```
Access to XMLHttpRequest at 'http://localhost:8000/api/v1/...' from origin 'http://localhost:5173' has been blocked by CORS policy
```

**解决**：

1. 确认 `.env` 里 `CORS_ORIGINS` 包含当前前端 origin（含端口）：

   ```ini
   CORS_ORIGINS=["http://localhost:5173"]
   ```

2. **改完 .env 必须重启后端**——配置只在启动时读。

3. JSON 数组的引号必须是双引号，写成单引号会报错。

---

## 8. SQLite "database is locked"

**现象**：并发请求时偶发 500，后端日志 `sqlite3.OperationalError: database is locked`。

**原因**：SQLite 写锁是全局的，多个 worker 同时写会互相阻塞。

**解决**（短期）：

- 减少并发：把 `uvicorn --workers N` 调成 1 或 2
- 启用 WAL 模式：

  ```python
  # backend/app/db/session.py
  from sqlalchemy import event
  engine = create_async_engine(settings.DATABASE_URL, ...)

  @event.listens_for(engine.sync_engine, "connect")
  def set_sqlite_pragma(dbapi_connection, connection_record):
      cursor = dbapi_connection.cursor()
      cursor.execute("PRAGMA journal_mode=WAL")
      cursor.execute("PRAGMA busy_timeout=5000")
      cursor.close()
  ```

**根本解决**：换 PostgreSQL。

---

## 9. Provider 缓存不刷新

**现象**：改了 LLM 配置（换 base_url 或 model_name）后，AI 调用还是用旧配置。

**根因**：`backend/app/services/llm_orchestrator.py` 的 `_providers` 字典用 `config_id` 作 key 缓存 provider，**没有失效机制**。

**临时解决**：重启后端。

**长期方案**（TODO）：

- 缓存 key 改成 `(config_id, model_name, base_url)` 复合
- 或者在 LLMConfig update 接口里主动 `del self._providers[config_id]`
- 或者加个 TTL 过期

---

## 10. 前端编辑富文本后切换章节，提示未保存

**现象**：编辑器里有改动但没保存，切换到别的页面会丢失。

**当前状态**：项目**没有"未保存"提示**——失不丢失看用户运气。

**解决**（用户）：用 Ctrl+S 手动保存（如果有快捷键）；或者点「AI 助手」会自动触发保存。

**解决**（开发）：加 beforeunload 监听 + 路由切换拦截 + 顶部"有未保存改动"提示条。

---

## 11. 测试数据库残留

**现象**：跑过 `pytest` 后，本地数据库被冲掉。

**原因**：`backend/tests/test_api.py` 用 `test_db.db` 临时库，但**测试结束后没有清理**。

**解决**：

```bash
rm backend/test_db.db
```

或者改测试用 in-memory SQLite（`:memory:`），不落盘。

---

## 12. 大纲/人物/章节数据莫名其妙清空

**现象**：原本有的数据没了，浏览器看不到。

**可能原因**：

1. **删了项目**：所有大纲/人物/章节通过 `cascade="all, delete-orphan"` 跟着删了。**这是设计行为，不可恢复**。
2. **数据库文件被替换**：`data/novel_agent.db` 被覆盖。检查是否有备份。
3. **误调删除接口**：前端有没有删除按钮？目前是删除章节/人物按钮，没有"删除项目"的快捷入口（要去项目列表删）。

**预防**：

- 删除项目时**前端加二次确认 + 警告**：会清空所有子资源
- 关键操作加"软删除"标记
- 定期备份 db

---

## 调试命令速查

```bash
# 看后端日志（如果用 uvicorn 直接跑）
# 直接看终端

# 看后端日志（如果用 systemd）
sudo journalctl -u novel-writing-agent -f --since "5 minutes ago"

# 直接看数据库
sqlite3 data/novel_agent.db
sqlite> .tables
sqlite> .schema llm_configs
sqlite> SELECT id, provider, base_url, model_name, default_params, rate_limit FROM llm_configs;

# 看 LLM 是否真能调通
curl -X POST http://localhost:5173/api/v1/llm-configs -H "Content-Type: application/json" -d '{
  "provider": "openai_compatible",
  "api_key": "sk-test",
  "base_url": "https://api.deepseek.com",
  "model_name": "deepseek-chat"
}'
# 然后调用 test 端点
curl -X POST http://localhost:5173/api/v1/llm-configs/<id>/test
```

---

## 还没解决的 TODO

按优先级排：

1. **LLM Provider 缓存按 `(config_id, model_name)` 维度失效** — 改了 LLM 配置不用重启
2. **前端 catch 块细粒度错误提示** — 把后端 error_code 透传
3. **SECRET_KEY 轮换机制** — 双重主密钥
4. **Alembic 迁移** — 表结构变更不再靠手动 SQL
5. **未保存改动提示** — 编辑器失焦保护
6. **大文档/项目列表的虚拟滚动** — 性能
7. **AI 流式续写的断线重连** — 网络异常恢复
8. **后端 health check 端点** — k8s/Nginx 探活
