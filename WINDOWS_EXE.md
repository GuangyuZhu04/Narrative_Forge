# Windows EXE 使用说明

构建产物位于：

```text
dist/NarrativeForge.exe
```

双击运行后，程序会启动本地 FastAPI 服务并自动打开浏览器。关闭程序窗口即可退出。

首次运行会在 exe 同目录下创建：

```text
data/novel_agent.db
data/uploads/
```

这些是本机运行数据，不应提交到 Git。

## 重新构建

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-windows-exe.ps1
```

脚本会构建前端、安装后端依赖与 PyInstaller，并重新生成 `dist/NarrativeForge.exe`。

## 可选环境变量

- `NARRATIVE_FORGE_PORT`：指定本地端口，默认从 `8765` 开始自动查找。
- `NARRATIVE_FORGE_NO_BROWSER=1`：启动时不自动打开浏览器。
- `NARRATIVE_FORGE_SECRET_KEY`：替换默认本机密钥。
- `NARRATIVE_FORGE_DATABASE_URL`：指定数据库连接串。
