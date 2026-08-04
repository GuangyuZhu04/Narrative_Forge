import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, verify_project_access
from app.core.security import encrypt_api_key
from app.models.audiobook import AudiobookConfig, AudiobookJob
from app.models.project import Project
from app.models.llm_config import LLMConfig
from app.schemas.audiobook import (
    AudiobookCharacterVoicesUpdate,
    AudiobookConfigResponse,
    AudiobookConfigUpdate,
    AudiobookJobCreate,
    AudiobookJobResponse,
    AudiobookPreviewRequest,
    AudiobookScopesResponse,
    AudiobookApiDocsParseRequest,
    AudiobookApiDocsParseResponse,
    AudiobookVoiceDesignRequest,
    AudiobookVoiceDesignResponse,
    AudiobookVoiceDeleteRequest,
    AudiobookVoiceDeleteResponse,
    AudiobookVoiceQueryRequest,
    AudiobookVoiceQueryResponse,
)
from app.services.audiobook_service import (
    AUDIOBOOK_ROOT,
    AudiobookValidationError,
    AudiobookVoiceServiceError,
    audiobook_service,
)

router = APIRouter()


def config_response(project_id: str, config: AudiobookConfig | None) -> AudiobookConfigResponse:
    if not config:
        return AudiobookConfigResponse(
            project_id=project_id,
            provider="openai_compatible",
            base_url="http://127.0.0.1:8001/v1",
            api_key_configured=False,
            model_name="tts-1",
            narrator_voice="alloy",
            character_voices={},
            speed=1.0,
            use_ffmpeg=True,
            max_chars_per_segment=800,
            request_timeout_seconds=180,
            requests_per_minute=20,
            comfyui_workflow=None,
            custom_request=None,
        )
    return AudiobookConfigResponse(
        id=config.id,
        project_id=config.project_id,
        provider=config.provider,
        base_url=config.base_url,
        api_key_configured=bool(config.api_key_encrypted),
        model_name=config.model_name,
        narrator_voice=config.narrator_voice,
        character_voices=config.character_voices or {},
        speed=config.speed,
        use_ffmpeg=config.use_ffmpeg,
        max_chars_per_segment=config.max_chars_per_segment,
        request_timeout_seconds=config.request_timeout_seconds,
        requests_per_minute=config.requests_per_minute,
        comfyui_workflow=config.comfyui_workflow,
        custom_request=config.custom_request,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


async def get_project_config(db: AsyncSession, project_id: str) -> AudiobookConfig | None:
    return (
        await db.execute(select(AudiobookConfig).where(AudiobookConfig.project_id == project_id))
    ).scalar_one_or_none()


async def job_response(
    db: AsyncSession,
    job: AudiobookJob,
    chapter_display_info=None,
) -> AudiobookJobResponse:
    if chapter_display_info is None:
        chapter_display_info = await audiobook_service.get_chapter_display_info(
            db, job.project_id
        )
    response = AudiobookJobResponse.model_validate(job)
    scope_info = chapter_display_info.get(job.scope_id or "")
    if job.scope_type == "chapter" and scope_info:
        response.scope_title = scope_info.title

    for artifact in response.output_files:
        suffix = Path(artifact.filename).suffix or ".mp3"
        chapter_info = chapter_display_info.get(artifact.chapter_id or "")
        if artifact.kind == "chapter" and chapter_info:
            artifact.title = chapter_info.title
            artifact.download_filename = (
                f"{chapter_info.position:03d}_"
                f"{audiobook_service.safe_filename(chapter_info.title)}{suffix}"
            )
        elif artifact.kind == "combined":
            artifact.title = response.scope_title
            artifact.download_filename = (
                f"{audiobook_service.safe_filename(response.scope_title)}{suffix}"
            )
        else:
            artifact.download_filename = artifact.filename
    return response


@router.get("/config", response_model=AudiobookConfigResponse)
async def get_config(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    return config_response(project_id, await get_project_config(db, project_id))


@router.put("/config", response_model=AudiobookConfigResponse)
async def update_config(
    project_id: str,
    data: AudiobookConfigUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    config = await get_project_config(db, project_id)
    if not config:
        config = AudiobookConfig(project_id=project_id)
        db.add(config)

    values = data.model_dump(exclude={"api_key"})
    if values.get("custom_request"):
        values["custom_request"] = audiobook_service.sanitize_request_secrets(
            values["custom_request"]
        )
        values["custom_request"].pop("requests_per_minute", None)
    for key, value in values.items():
        setattr(config, key, value)
    if data.api_key is not None:
        config.api_key_encrypted = (
            encrypt_api_key(data.api_key.strip()) if data.api_key.strip() else None
        )
    try:
        audiobook_service.validate_config(config)
    except AudiobookValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(config)
    return config_response(project_id, config)


@router.patch("/config/character-voices", response_model=AudiobookConfigResponse)
async def update_character_voices(
    project_id: str,
    data: AudiobookCharacterVoicesUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    config = await get_project_config(db, project_id)
    if not config:
        config = AudiobookConfig(project_id=project_id)
        db.add(config)

    config.character_voices = data.character_voices
    await db.commit()
    await db.refresh(config)
    return config_response(project_id, config)


@router.post("/config/parse-docs", response_model=AudiobookApiDocsParseResponse)
async def parse_api_documentation(
    project_id: str,
    data: AudiobookApiDocsParseRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    llm_config = await db.get(LLMConfig, data.llm_config_id)
    if not llm_config:
        raise HTTPException(status_code=400, detail="所选 LLM 配置不存在")
    if not llm_config.is_active:
        raise HTTPException(status_code=400, detail="所选 LLM 配置未启用")
    try:
        result = await audiobook_service.parse_api_documentation(
            data.llm_config_id, data.api_documentation
        )
        return AudiobookApiDocsParseResponse.model_validate(result)
    except AudiobookValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM 解析 API 文档失败：{exc}") from exc


@router.post("/preview")
async def preview_voice(
    project_id: str,
    data: AudiobookPreviewRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    try:
        content = await audiobook_service.preview(db, project_id, data.text, data.voice)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'inline; filename="preview.mp3"'},
    )


@router.post("/voices/query", response_model=AudiobookVoiceQueryResponse)
async def query_available_voices(
    project_id: str,
    data: AudiobookVoiceQueryRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    try:
        result = await audiobook_service.query_voices(db, project_id, data.voice_type)
        return AudiobookVoiceQueryResponse.model_validate(result)
    except AudiobookValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AudiobookVoiceServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/voices/design", response_model=AudiobookVoiceDesignResponse)
async def design_voice(
    project_id: str,
    data: AudiobookVoiceDesignRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    try:
        result = await audiobook_service.design_voice(
            db,
            project_id,
            prompt=data.prompt,
            preview_text=data.preview_text,
            voice_id=data.voice_id,
            aigc_watermark=data.aigc_watermark,
        )
        return AudiobookVoiceDesignResponse.model_validate(result)
    except AudiobookValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AudiobookVoiceServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/voices/delete", response_model=AudiobookVoiceDeleteResponse)
async def delete_voice(
    project_id: str,
    data: AudiobookVoiceDeleteRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    try:
        result = await audiobook_service.delete_voice(
            db,
            project_id,
            voice_id=data.voice_id,
            voice_type=data.voice_type,
        )
        return AudiobookVoiceDeleteResponse.model_validate(result)
    except AudiobookValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AudiobookVoiceServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/scopes", response_model=AudiobookScopesResponse)
async def get_scopes(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    return await audiobook_service.get_scopes(db, project_id)


@router.get("/jobs")
async def list_jobs(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    jobs = list(
        (
            await db.execute(
                select(AudiobookJob)
                .where(AudiobookJob.project_id == project_id)
                .order_by(AudiobookJob.created_at.desc(), AudiobookJob.id.desc())
            )
        )
        .scalars()
        .all()
    )
    chapter_display_info = await audiobook_service.get_chapter_display_info(db, project_id)
    return {
        "data": [
            (await job_response(db, job, chapter_display_info)).model_dump()
            for job in jobs
        ]
    }


@router.post("/jobs", response_model=AudiobookJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    project_id: str,
    data: AudiobookJobCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    if data.scope_type != "book" and not data.scope_id:
        raise HTTPException(status_code=400, detail="请选择生成范围")
    try:
        job = await audiobook_service.create_job(
            db,
            project_id,
            data.scope_type,
            data.scope_id,
            data.llm_config_id,
        )
    except AudiobookValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audiobook_service.start_job(job.id)
    return await job_response(db, job)


@router.get("/jobs/{job_id}", response_model=AudiobookJobResponse)
async def get_job(
    project_id: str,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    job = await db.get(AudiobookJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(status_code=404, detail="有声书任务不存在")
    return await job_response(db, job)


@router.post("/jobs/{job_id}/cancel", response_model=AudiobookJobResponse)
async def cancel_job(
    project_id: str,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    job = await db.get(AudiobookJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(status_code=404, detail="有声书任务不存在")
    if job.status in {"queued", "processing"}:
        job.status = "cancelled"
        job.current_chapter_title = None
        job.completed_at = datetime.now()
        await db.commit()
        await db.refresh(job)
        audiobook_service.cancel_task(job.id)
        shutil.rmtree(AUDIOBOOK_ROOT / project_id / job.id, ignore_errors=True)
    return await job_response(db, job)


@router.get("/jobs/{job_id}/files/{filename}")
async def download_file(
    project_id: str,
    job_id: str,
    filename: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    job = await db.get(AudiobookJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(status_code=404, detail="有声书任务不存在")
    artifact = next(
        (
            item
            for item in (job.output_files or [])
            if item.get("filename") == filename
        ),
        None,
    )
    if artifact is None or Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="音频文件不存在")
    path = AUDIOBOOK_ROOT / project_id / job_id / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="音频文件不存在")
    response = await job_response(db, job)
    response_artifact = next(
        (item for item in response.output_files if item.filename == filename),
        None,
    )
    download_filename = (
        response_artifact.download_filename if response_artifact else filename
    )
    return FileResponse(
        path,
        media_type="audio/mpeg",
        filename=download_filename or filename,
    )


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    project_id: str,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    job = await db.get(AudiobookJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(status_code=404, detail="有声书任务不存在")
    if job.status in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="请先取消正在执行的任务")
    await db.delete(job)
    await db.commit()
    shutil.rmtree(AUDIOBOOK_ROOT / project_id / job_id, ignore_errors=True)
