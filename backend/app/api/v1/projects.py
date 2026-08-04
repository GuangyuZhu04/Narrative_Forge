from pathlib import Path
import shutil
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_db
from app.models.project import Project
from app.models.audiobook import AudiobookJob
from app.services.audiobook_service import AUDIOBOOK_ROOT, audiobook_service
from app.services.project_service import project_service
from app.schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    PaginatedResponse,
)
from app.core.exceptions import ProjectNotFoundException

router = APIRouter()

UPLOAD_ROOT = Path("data/uploads")
PROJECT_COVER_ROOT = UPLOAD_ROOT / "projects"
IMAGE_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_PROJECT_COVER_BYTES = 10 * 1024 * 1024


def _upload_url_to_path(upload_url: str | None) -> Path | None:
    if not upload_url or not upload_url.startswith("/uploads/"):
        return None
    relative_path = upload_url.removeprefix("/uploads/").lstrip("/")
    path = UPLOAD_ROOT / relative_path
    try:
        path.resolve().relative_to(UPLOAD_ROOT.resolve())
    except ValueError:
        return None
    return path


@router.get("", response_model=PaginatedResponse)
async def list_projects(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    projects, total = await project_service.get_list(
        db, status=status, page=page, page_size=page_size
    )
    return PaginatedResponse(
        data=[ProjectResponse.model_validate(p).model_dump() for p in projects],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str, db: AsyncSession = Depends(get_db)
):
    project = await project_service.get_by_id(db, project_id)
    if not project:
        raise ProjectNotFoundException()
    return project


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate, db: AsyncSession = Depends(get_db)
):
    project = await project_service.create(db, data)
    return project


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
):
    project = await project_service.update(db, project_id, data)
    if not project:
        raise ProjectNotFoundException()
    return project


@router.put("/{project_id}/cover", response_model=ProjectResponse)
async def upload_project_cover(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    project = await project_service.get_by_id(db, project_id)
    if not project:
        raise ProjectNotFoundException()

    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    extension = IMAGE_CONTENT_TYPES.get(content_type)
    if not extension:
        raise HTTPException(status_code=400, detail="仅支持 JPG、PNG、WEBP 或 GIF 图片")

    content = await request.body()
    if not content:
        raise HTTPException(status_code=400, detail="封面内容不能为空")
    if len(content) > MAX_PROJECT_COVER_BYTES:
        raise HTTPException(status_code=400, detail="封面大小不能超过 10MB")

    upload_dir = PROJECT_COVER_ROOT / project_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    image_path = upload_dir / f"cover_{uuid4().hex}{extension}"
    image_path.write_bytes(content)

    old_cover_path = _upload_url_to_path(project.cover_url)
    project.cover_url = f"/uploads/projects/{project_id}/{image_path.name}"
    await db.commit()
    await db.refresh(project)

    if old_cover_path and old_cover_path.exists() and old_cover_path != image_path:
        old_cover_path.unlink()
    return project


@router.delete("/{project_id}/cover", response_model=ProjectResponse)
async def delete_project_cover(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    project = await project_service.get_by_id(db, project_id)
    if not project:
        raise ProjectNotFoundException()

    cover_path = _upload_url_to_path(project.cover_url)
    if cover_path and cover_path.exists():
        cover_path.unlink()

    project.cover_url = None
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str, db: AsyncSession = Depends(get_db)
):
    project: Project | None = await project_service.get_by_id(db, project_id)
    cover_path = _upload_url_to_path(project.cover_url if project else None)
    audiobook_job_ids = list(
        (
            await db.execute(
                select(AudiobookJob.id).where(AudiobookJob.project_id == project_id)
            )
        ).scalars().all()
    )
    deleted = await project_service.delete(db, project_id)
    if not deleted:
        raise ProjectNotFoundException()
    if cover_path and cover_path.exists():
        cover_path.unlink()
    for job_id in audiobook_job_ids:
        audiobook_service.cancel_task(job_id)
    shutil.rmtree(AUDIOBOOK_ROOT / project_id, ignore_errors=True)
