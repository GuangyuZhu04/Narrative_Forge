# Windows EXE 使用说明

2026-09-10 更新：加入文字高亮和阅读模式，支持阅读主题、排版、目录搜索、书签、进度记忆和按屏翻页。旧数据库自动增加章节标注字段。使用方式见 [文字高亮与阅读模式](docs/reading-highlights.md)。

2026-09-09 更新：同步新版系统提示词，并修复桌面包首页及工作区深层链接返回 404 的问题。详见 [提示词更新说明](docs/system-prompts-2026-09-09.md)。

可分发压缩包为 `dist/NarrativeForge-Windows.zip`，解压后运行其中的 `NarrativeForge.exe`；同目录 `.sha256` 文件用于校验压缩包及 EXE。

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

需要先安装：

- Node.js LTS（包含 `npm`）
- Python 3.11 或更高版本

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-windows-exe.ps1
```

脚本会构建前端、安装后端依赖与 PyInstaller，并重新生成 `dist/NarrativeForge.exe`。

如果 `frontend/node_modules` 已存在但缺少 `tsc` 或 `vite`，脚本会自动使用 `npm ci` 重新安装前端依赖，避免依赖目录残缺导致打包失败。

打包后的 exe 会内置 `frontend/dist`，启动时挂载到本地 FastAPI 服务。首页、设置页和项目工作区的直接访问及刷新均可返回前端页面；不存在的 API 和资源仍返回 404。

## 可选环境变量

- `NARRATIVE_FORGE_PORT`：指定本地端口，默认从 `8765` 开始自动查找。
- `NARRATIVE_FORGE_NO_BROWSER=1`：启动时不自动打开浏览器。
- `NARRATIVE_FORGE_SECRET_KEY`：替换默认本机密钥。
- `NARRATIVE_FORGE_DATABASE_URL`：指定数据库连接串。
