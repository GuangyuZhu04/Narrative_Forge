from contextlib import asynccontextmanager
from pathlib import Path
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.core.config import settings
from app.core.exceptions import AppException
from app.api.v1 import (
    projects,
    outlines,
    characters,
    scenes,
    chapters,
    analysis,
    discussions,
    llm_config,
    export,
    system_settings,
)
from app.db.session import engine
from app.models.base import Base


def find_frontend_dist() -> Path | None:
    candidates: list[Path] = []
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        candidates.append(Path(bundled_root) / "frontend_dist")

    repo_root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            repo_root / "frontend" / "dist",
            Path.cwd() / "frontend_dist",
        ]
    )

    for candidate in dict.fromkeys(candidates):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def mount_frontend(app: FastAPI) -> None:
    frontend_dist = find_frontend_dist()
    if not frontend_dist:
        return

    assets_dir = frontend_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    async def serve_frontend_index():
        return FileResponse(frontend_dist / "index.html")

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_frontend_path(path: str):
        if path.startswith(("api/", "uploads/")):
            raise HTTPException(status_code=404)

        target = (frontend_dist / path).resolve()
        if frontend_dist.resolve() in (target, *target.parents) and target.is_file():
            return FileResponse(target)
        return FileResponse(frontend_dist / "index.html")


async def ensure_runtime_schema(conn):
    result = await conn.execute(text("PRAGMA table_info(characters)"))
    columns = {row[1] for row in result.fetchall()}
    if "biography" not in columns:
        await conn.execute(text("ALTER TABLE characters ADD COLUMN biography TEXT"))
    if "setting_collection" not in columns:
        await conn.execute(
            text("ALTER TABLE characters ADD COLUMN setting_collection TEXT")
        )
    if "sort_order" not in columns:
        await conn.execute(
            text("ALTER TABLE characters ADD COLUMN sort_order INTEGER DEFAULT 0")
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_runtime_schema(conn)
    yield


app = FastAPI(title="Novel Writing Agent API", version="0.1.0", lifespan=lifespan)
app.mount("/uploads", StaticFiles(directory="data/uploads", check_dir=False), name="uploads")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api/v1/projects", tags=["Projects"])
app.include_router(outlines.router, prefix="/api/v1/projects/{project_id}/outlines", tags=["Outlines"])
app.include_router(characters.router, prefix="/api/v1/projects/{project_id}/characters", tags=["Characters"])
app.include_router(scenes.router, prefix="/api/v1/projects/{project_id}/scenes", tags=["Scenes"])
app.include_router(chapters.router, prefix="/api/v1/projects/{project_id}/chapters", tags=["Chapters"])
app.include_router(discussions.router, prefix="/api/v1/projects/{project_id}/discussions", tags=["Discussions"])
app.include_router(analysis.router, prefix="/api/v1/projects/{project_id}/analysis", tags=["Analysis"])
app.include_router(export.router, prefix="/api/v1/projects/{project_id}/export", tags=["Export"])
app.include_router(llm_config.router, prefix="/api/v1/llm-configs", tags=["LLM Config"])
app.include_router(
    system_settings.router,
    prefix="/api/v1/system-settings",
    tags=["System Settings"],
)
mount_frontend(app)


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "error_code": exc.error_code},
    )
