# Novel Writing Agent — 部署文档

> 本文档涵盖环境变量、生产部署、安全建议与运维要点。

---

## 1. 环境变量

后端通过 `backend/.env` 文件（或系统环境变量）注入配置，由 `backend/app/core/config.py` 读取。

| 变量 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `DATABASE_URL` | 否 | `sqlite+aiosqlite:///./data/novel_agent.db` | SQLAlchemy 数据库连接串 |
| `SECRET_KEY` | **是（生产）** | `change-me-in-production` | API 密钥加密的主密钥，**生产前必改** |
| `DEBUG` | 否 | `True` | 调试模式。生产务必设为 `False`，会关闭 SQL 详细日志 |
| `CORS_ORIGINS` | 否 | `["http://localhost:5173"]` | 允许跨域的前端源（JSON 数组格式） |

### 1.1 `SECRET_KEY` 必须换

`SECRET_KEY` 是 LLM API 密钥加密的根密钥。**默认的 `"change-me-in-production"` 是占位符**，任何拿到 `data/novel_agent.db` + 默认 `SECRET_KEY` 的人都能解出所有 LLM API 密钥。

**生产部署前**：

```bash
# 生成 32 字节随机密钥并 base64 编码
python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

把输出写入 `.env`：

```ini
SECRET_KEY=<上面生成的字符串>
```

### 1.2 `DATABASE_URL` 切换到 PostgreSQL（推荐）

SQLite 适合单用户本地开发，**生产推荐换 PostgreSQL**：

```ini
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/novel_agent
```

⚠️ 切换后**表结构需要重新建**（项目目前用 `Base.metadata.create_all` 启动时建表）。生产建议接入 Alembic 做迁移（见 `docs/development.md` 第 8 节 TODO）。

### 1.3 `DEBUG=False` 的影响

设为 `False` 会关闭 SQLAlchemy 的 echo 日志输出，错误堆栈也不会自动返回给客户端（FastAPI 默认行为）。**生产环境应保持 False**。

### 1.4 `CORS_ORIGINS` 配置多源

JSON 数组格式：

```ini
CORS_ORIGINS=["https://your-domain.com","https://www.your-domain.com"]
```

**不要用 `*`**，否则会与 `allow_credentials=True` 冲突。

---

## 2. 部署模式

### 2.1 单机部署（推荐用于自托管）

```
浏览器 (HTTPS) → Nginx (反向代理) → Uvicorn (FastAPI) → SQLite
                                       ↓
                                    远程 LLM API
```

**步骤**：

1. 准备服务器（Ubuntu 22.04+ 推荐）
2. 装 Python 3.11+ 和 Node 18+（构建前端用一次就行）
3. 拉代码
4. 后端：

   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```

5. 构建前端：

   ```bash
   cd frontend
   npm install
   npm run build
   # 产物在 frontend/dist/
   ```

6. 配置 `.env`（见第 1 节）

7. 起后端（用 gunicorn 或 uvicorn 都行）：

   ```bash
   # 开发/小流量：uvicorn
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2

   # 生产：gunicorn（更稳）
   pip install gunicorn
   gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
   ```

8. 配置 Nginx 反代 + 静态文件托管（推荐）：

   ```nginx
   server {
       listen 80;
       server_name your-domain.com;
       return 301 https://$server_name$request_uri;
   }

   server {
       listen 443 ssl http2;
       server_name your-domain.com;

       ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
       ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

       # 前端静态文件
       root /opt/novel-writing-agent/frontend/dist;
       index index.html;

       # API 反代
       location /api/ {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_read_timeout 300s;   # LLM 调用可能慢
       }

       # SPA fallback
       location / {
           try_files $uri $uri/ /index.html;
       }
   }
   ```

### 2.2 Docker 部署（计划中）

`Dockerfile` 和 `docker-compose.yml` 尚未提供。计划结构：

```yaml
# docker-compose.yml（草案）
services:
  backend:
    build: ./backend
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/novel
      - SECRET_KEY=${SECRET_KEY}
      - DEBUG=False
      - CORS_ORIGINS=["https://your-domain.com"]
    volumes:
      - ./data:/app/data
    depends_on:
      - db

  frontend:
    build: ./frontend
    # 或直接挂载 dist 到 nginx

  db:
    image: postgres:16
    environment:
      - POSTGRES_PASSWORD=postgres
    volumes:
      - pgdata:/var/lib/postgresql/data
```

### 2.3 systemd 服务

```ini
# /etc/systemd/system/novel-writing-agent.service
[Unit]
Description=Novel Writing Agent
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/novel-writing-agent/backend
Environment="PATH=/opt/novel-writing-agent/backend/.venv/bin"
ExecStart=/opt/novel-writing-agent/backend/.venv/bin/gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker -b 127.0.0.1:8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now novel-writing-agent
sudo systemctl status novel-writing-agent
```

---

## 3. 安全清单

### 3.1 必须做

- [x] **改 `SECRET_KEY`**：用 `secrets.token_bytes(32)` 生成
- [x] **`DEBUG=False`**：生产环境
- [x] **HTTPS**：用 Let's Encrypt 或反代处理
- [x] **限制 CORS**：不要用 `*`
- [x] **不要把 `data/novel_agent.db` 提交到 git**（含加密后的密钥）
- [x] **不要把 `.env` 提交到 git**（含 SECRET_KEY）
- [x] **不要把 `frontend/dist/` 提交到 git**（构建产物）

### 3.2 推荐做

- [ ] **数据库独立用户**：PostgreSQL 给应用单独建个用户，权限只到 `novel` 库
- [ ] **日志脱敏**：记录 LLM 调用时不要打印完整 prompt/response
- [ ] **API 速率限制**：现在用 LLM 层的 token bucket，但**应用层 HTTP 还没限流**——防爬可以加 Nginx limit_req 或 API gateway
- [ ] **备份 SQLite 文件**：定时 `cp data/novel_agent.db backup/`
- [ ] **数据库加密**：PostgreSQL 用 `pgcrypto` 扩展加密敏感字段；SQLite 加密需要 SQLCipher
- [ ] **审计日志**：记录谁在什么时间调用了什么接口（多用户化后必须）

### 3.3 当前已知的安全债

| 风险 | 描述 | 建议修复 |
|------|------|----------|
| SECRET_KEY 默认值 | 默认值会泄露所有 key | 生产前必改；CI 加 lint 阻止默认值入库 |
| 数据无加密备份 | SQLite 文件明文 | 加密备份（gpg / 7z 密码） |
| 密钥轮换机制缺失 | 改 SECRET_KEY 后旧数据全解不开 | 加"双重主密钥"支持：先尝试新 key 解，失败再用旧 key 重加密 |
| 多用户隔离缺失 | 单租户，无 auth | 引入 JWT + user_id 外键 |
| 前端错误信息过少 | catch 块统一提示，无法区分错误类型 | 透传后端 error_code，前端按 code 分支处理 |

### 3.4 `data/` 目录一定要 `.gitignore`

确认 `.gitignore` 里有：

```gitignore
data/
*.db
*.db-journal
.env
```

如果 `data/novel_agent.db` 已经被 commit 过历史，**用 `git rm --cached data/novel_agent.db` 取消追踪**，但保留本地文件。

---

## 4. 备份与恢复

### 4.1 备份

```bash
# 简单粗暴：直接复制 db 文件
cp data/novel_agent.db backup/novel_agent_$(date +%Y%m%d).db

# 安全备份：先停服务（SQLite 文件可能被占用）
sudo systemctl stop novel-writing-agent
tar czf backup-$(date +%Y%m%d).tar.gz data/ .env
sudo systemctl start novel-writing-agent
```

### 4.2 恢复

```bash
sudo systemctl stop novel-writing-agent
cp backup/novel_agent_20260101.db data/novel_agent.db
sudo systemctl start novel-writing-agent
```

### 4.3 灾难恢复

- 数据库损坏：`rm data/novel_agent.db`，重启后端会自动重建空库（**所有用户数据会丢**，除非有备份）
- SECRET_KEY 丢失：所有 LLM 配置**无法解密**。需要让用户重新输入 API key。

> 💡 强烈建议在文档里提醒用户：**SECRET_KEY 一旦丢失或更换，必须重新配置所有 LLM**。

---

## 5. 监控与日志

### 5.1 应用日志

目前后端日志直接打 stdout。生产环境推荐：

- **journald**（systemd 自带）：`journalctl -u novel-writing-agent -f`
- **Docker logs**：`docker logs -f <container>`
- **推送到 ELK / Loki**：在 main.py 里加 `logstash` handler 或 `promtail`

### 5.2 关键监控指标

- **LLM 调用成功率 / 延迟**（按 provider 拆）
- **API 端点 P50/P99 延迟**（按路由拆）
- **数据库连接池使用率**（SQLAlchemy 可暴露）
- **磁盘空间**（SQLite 单文件可能膨胀）
- **LLM API 配额使用情况**（provider 控制台查）

### 5.3 健康检查端点

目前**没有专门的 health check 接口**。可以加：

```python
# backend/app/api/v1/health.py
@router.get("/health")
async def health():
    return {"status": "ok"}
```

挂到 `/api/v1/health`，Nginx / k8s liveness probe 用。

---

## 6. 升级流程

### 6.1 后端升级

```bash
cd /opt/novel-writing-agent
git pull
cd backend
source .venv/bin/activate
pip install -e ".[dev]"  # 装新依赖
sudo systemctl restart novel-writing-agent
journalctl -u novel-writing-agent -f  # 看启动日志
```

### 6.2 前端升级

```bash
cd /opt/novel-writing-agent/frontend
git pull
npm install
npm run build
# dist/ 已被 nginx 直接服务，无需重启 nginx（nginx 会自动读新文件）
```

### 6.3 数据库 schema 变更

⚠️ **本项目目前没有 Alembic**。schema 变更需要：

1. 在 `models/*.py` 改模型
2. 手动写 SQL 迁移（如果生产有数据）
3. 或者清空 db 重新建（**会丢数据**）

短期方案：上线新 schema 时先把 `data/novel_agent.db` 备份好，确认新 schema 兼容老数据。

长期方案：**接入 Alembic**，见 `docs/development.md` 第 8 节。

---

## 7. 常见部署错误

| 现象 | 原因 | 解决 |
|------|------|------|
| 502 Bad Gateway | 后端没启动 / 端口不对 | `systemctl status novel-writing-agent` |
| 504 Gateway Timeout | LLM 调用超时 | Nginx `proxy_read_timeout` 调大（默认 60s） |
| CORS 错误 | `CORS_ORIGINS` 没配前端域名 | 改成实际前端 origin，**重启后端** |
| "无法连接到 LLM" | LLM API 域名被墙 | 配置代理或换 LLM 服务商 |
| 加密解密失败 | 改过 SECRET_KEY 但没重新配 LLM | 重新添加 LLM 配置 |
| 数据库 locked | SQLite 写并发 | 换 PostgreSQL，或加 `WAL` 模式（`PRAGMA journal_mode=WAL`） |

---

## 8. 容量与性能基线

未做正式压测，以下是粗略参考（单 worker / 单 LLM 调用）：

| 指标 | 数值 |
|------|------|
| 启动时间 | ~2s |
| 内存占用（空载） | ~150MB |
| LLM chat 调用延迟 | 2-10s（取决于 provider） |
| LLM stream 调用首字延迟 | <1s |
| SQLite 写入吞吐 | ~1000 ops/s（小数据） |
| 并发用户 | 建议 ≤10（SQLite 写锁是瓶颈） |

**生产建议**：

- 单机 ≤ 5 用户：SQLite + 2 workers OK
- 5-50 用户：PostgreSQL + 4 workers
- > 50 用户：考虑加 Redis 做 LLM 响应缓存

---

## 9. 卸载

```bash
sudo systemctl stop novel-writing-agent
sudo systemctl disable novel-writing-agent
sudo rm /etc/systemd/system/novel-writing-agent.service
sudo rm -rf /opt/novel-writing-agent
```

数据库文件如果想彻底清除：`rm -rf /opt/novel-writing-agent/data/`。
