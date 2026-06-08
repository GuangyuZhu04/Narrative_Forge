import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, verify_project_access
from app.models.project import Project
from app.services.consistency_service import consistency_service
from app.schemas.analysis import (
    AnalysisChapterOptionResponse,
    ConsistencyAnalysisRequest,
    AnalysisReportResponse,
)
from app.core.exceptions import ChapterNotFoundException, NotFoundException

router = APIRouter()


@router.post("/consistency")
async def analyze_consistency(
    project_id: str,
    data: ConsistencyAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    results = await consistency_service.analyze_chapter(
        db,
        project_id,
        data.chapter_id,
        data.llm_config_id,
        data.dimensions,
    )
    if results is None:
        raise ChapterNotFoundException()
    return results


@router.post("/consistency/stream")
async def stream_consistency(
    project_id: str,
    data: ConsistencyAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    chapter = await consistency_service.get_active_chapter(
        db, project_id, data.chapter_id
    )
    if not chapter:
        raise ChapterNotFoundException()

    context = await consistency_service._assemble_context(
        db, project_id, chapter
    )
    dimension = data.dimensions[0] if data.dimensions else "character"
    characters = await consistency_service.get_project_characters(db, project_id)
    context["character_profiles"] = consistency_service.format_character_profiles(
        characters
    )

    async def event_generator():
        async for chunk in consistency_service.stream_analyze(
            db, data.llm_config_id, context, dimension
        ):
            yield f"event: chunk\ndata: {json.dumps({'content': chunk})}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_generator(), media_type="text/event-stream"
    )


@router.get("/chapters")
async def list_analysis_chapters(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    chapters = await consistency_service.get_active_chapter_options(db, project_id)
    return {
        "data": [
            AnalysisChapterOptionResponse.model_validate(chapter).model_dump()
            for chapter in chapters
        ]
    }


@router.get("/reports")
async def list_reports(
    project_id: str,
    chapter_id: str | None = None,
    analysis_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    reports = await consistency_service.get_reports(
        db, project_id, chapter_id, analysis_type
    )
    response_data = []
    for report in reports:
        item = AnalysisReportResponse.model_validate(report).model_dump()
        item["chapter_title"] = await consistency_service.get_report_chapter_title(
            db, report
        )
        response_data.append(item)
    return {
        "data": response_data
    }


@router.get("/reports/{report_id}", response_model=AnalysisReportResponse)
async def get_report(
    project_id: str,
    report_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    report = await consistency_service.get_report(db, report_id)
    if not report or report.project_id != project_id:
        raise NotFoundException(detail="分析报告不存在", error_code="NOT_FOUND")
    item = AnalysisReportResponse.model_validate(report).model_dump()
    item["chapter_title"] = await consistency_service.get_report_chapter_title(
        db, report
    )
    if item["chapter_title"] is None:
        raise NotFoundException(detail="分析报告不存在", error_code="NOT_FOUND")
    return item
