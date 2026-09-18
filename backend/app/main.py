from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    audiobook,
    novel_agent,
)
from app.db.session import engine
from app.models.base import Base
from app.services.audiobook_service import audiobook_service


async def ensure_runtime_schema(conn):
    chapter_result = await conn.execute(text("PRAGMA table_info(chapters)"))
    chapter_columns = {row[1] for row in chapter_result.fetchall()}
    if "highlights" not in chapter_columns:
        await conn.execute(text("ALTER TABLE chapters ADD COLUMN highlights JSON NOT NULL DEFAULT '[]'"))

    character_result = await conn.execute(text("PRAGMA table_info(characters)"))
    character_columns = {row[1] for row in character_result.fetchall()}
    if "biography" not in character_columns:
        await conn.execute(text("ALTER TABLE characters ADD COLUMN biography TEXT"))
    if "setting_collection" not in character_columns:
        await conn.execute(
            text("ALTER TABLE characters ADD COLUMN setting_collection TEXT")
        )
    if "sort_order" not in character_columns:
        await conn.execute(
            text("ALTER TABLE characters ADD COLUMN sort_order INTEGER DEFAULT 0")
        )

    project_result = await conn.execute(text("PRAGMA table_info(projects)"))
    project_columns = {row[1] for row in project_result.fetchall()}
    if "cover_url" not in project_columns:
        await conn.execute(text("ALTER TABLE projects ADD COLUMN cover_url VARCHAR(500)"))

    audiobook_result = await conn.execute(text("PRAGMA table_info(audiobook_configs)"))
    audiobook_columns = {row[1] for row in audiobook_result.fetchall()}
    if audiobook_columns and "custom_request" not in audiobook_columns:
        await conn.execute(text("ALTER TABLE audiobook_configs ADD COLUMN custom_request JSON"))
    if audiobook_columns and "use_ffmpeg" not in audiobook_columns:
        await conn.execute(
            text("ALTER TABLE audiobook_configs ADD COLUMN use_ffmpeg BOOLEAN DEFAULT 1")
        )
    if audiobook_columns and "managed_voices" not in audiobook_columns:
        await conn.execute(
            text("ALTER TABLE audiobook_configs ADD COLUMN managed_voices JSON DEFAULT '[]'")
        )
    if audiobook_columns and "deleted_voice_ids" not in audiobook_columns:
        await conn.execute(
            text("ALTER TABLE audiobook_configs ADD COLUMN deleted_voice_ids JSON DEFAULT '[]'")
        )
    if audiobook_columns and "requests_per_minute" not in audiobook_columns:
        await conn.execute(
            text(
                "ALTER TABLE audiobook_configs "
                "ADD COLUMN requests_per_minute INTEGER DEFAULT 20"
            )
        )

    audiobook_job_result = await conn.execute(text("PRAGMA table_info(audiobook_jobs)"))
    audiobook_job_columns = {row[1] for row in audiobook_job_result.fetchall()}
    if audiobook_job_columns and "script_llm_config_id" not in audiobook_job_columns:
        await conn.execute(
            text("ALTER TABLE audiobook_jobs ADD COLUMN script_llm_config_id VARCHAR(100)")
        )
    if audiobook_job_columns and "speech_scripts" not in audiobook_job_columns:
        await conn.execute(
            text("ALTER TABLE audiobook_jobs ADD COLUMN speech_scripts JSON DEFAULT '{}'")
        )
    if audiobook_job_columns and "segment_tasks" not in audiobook_job_columns:
        await conn.execute(
            text("ALTER TABLE audiobook_jobs ADD COLUMN segment_tasks JSON DEFAULT '[]'")
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_runtime_schema(conn)
    await audiobook_service.resume_pending_jobs()
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
app.include_router(novel_agent.router, prefix="/api/v1/projects/{project_id}/novel-agent", tags=["Novel Agent"])
app.include_router(discussions.router, prefix="/api/v1/projects/{project_id}/discussions", tags=["Discussions"])
app.include_router(analysis.router, prefix="/api/v1/projects/{project_id}/analysis", tags=["Analysis"])
app.include_router(export.router, prefix="/api/v1/projects/{project_id}/export", tags=["Export"])
app.include_router(
    audiobook.router,
    prefix="/api/v1/projects/{project_id}/audiobook",
    tags=["Audiobook"],
)
app.include_router(llm_config.router, prefix="/api/v1/llm-configs", tags=["LLM Config"])
app.include_router(
    system_settings.router,
    prefix="/api/v1/system-settings",
    tags=["System Settings"],
)


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "error_code": exc.error_code},
    )
