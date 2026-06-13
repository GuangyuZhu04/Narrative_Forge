from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", app_dir())).resolve()
    return app_dir()


def frontend_dist_dir(root: Path) -> Path | None:
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(bundle_dir() / "frontend_dist")
    candidates.append(root / "frontend" / "dist")

    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    return None


def find_free_port(start: int = 8765, attempts: int = 100) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No free local port found.")


def open_browser_later(url: str) -> None:
    def _open() -> None:
        time.sleep(1.2)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    root = app_dir()
    os.chdir(root)
    data_dir = root / "data"
    uploads_dir = data_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    frontend_dir = frontend_dist_dir(root)
    if frontend_dir:
        os.environ["NARRATIVE_FORGE_FRONTEND_DIST"] = str(frontend_dir)

    os.environ["DATABASE_URL"] = os.environ.get(
        "NARRATIVE_FORGE_DATABASE_URL",
        f"sqlite+aiosqlite:///{(data_dir / 'novel_agent.db').as_posix()}",
    )
    os.environ["SECRET_KEY"] = os.environ.get(
        "NARRATIVE_FORGE_SECRET_KEY",
        "change-me-in-production",
    )
    os.environ["DEBUG"] = os.environ.get("NARRATIVE_FORGE_DEBUG", "False")

    requested_port = os.environ.get("NARRATIVE_FORGE_PORT")
    port = int(requested_port) if requested_port else find_free_port()
    os.environ["CORS_ORIGINS"] = os.environ.get(
        "NARRATIVE_FORGE_CORS_ORIGINS",
        f'["http://127.0.0.1:{port}"]',
    )
    url = f"http://127.0.0.1:{port}"

    print(f"文脉工坊已启动：{url}")
    print("关闭此窗口即可退出程序。")
    if os.environ.get("NARRATIVE_FORGE_NO_BROWSER") != "1":
        open_browser_later(url)
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
