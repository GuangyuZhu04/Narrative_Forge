from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, verify_project_access
from app.models.project import Project
from app.services.export_service import export_service
from app.schemas.export import ExportRequest
from app.core.exceptions import ProjectNotFoundException

router = APIRouter()


@router.post("")
async def export_project(
    project_id: str,
    data: ExportRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    content, filename, content_type = await export_service.export_project(
        db, project_id, data.format, data.options
    )
    if not content:
        raise ProjectNotFoundException()

    encoded_filename = quote(filename)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        "Content-Type": content_type,
    }
    return Response(content=content, headers=headers)
