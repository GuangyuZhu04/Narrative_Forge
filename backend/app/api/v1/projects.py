from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.project_service import project_service
from app.schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    PaginatedResponse,
)
from app.core.exceptions import ProjectNotFoundException

router = APIRouter()


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


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str, db: AsyncSession = Depends(get_db)
):
    deleted = await project_service.delete(db, project_id)
    if not deleted:
        raise ProjectNotFoundException()
