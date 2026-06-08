import json
import re

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, verify_project_access
from app.llm.providers.base import LLMContentFilteredError, LLMOutputTruncatedError
from app.models.chapter import Chapter
from app.models.project import Project
from app.services.chapter_service import NOVEL_WRITE_MAX_TOKENS, chapter_service
from app.services.llm_orchestrator import llm_orchestrator
from app.services.system_prompt_service import NOVEL_POLISH_DEFAULT_SUGGESTIONS_KEY
from app.schemas.chapter import (
    ChapterCreate,
    ChapterUpdate,
    ChapterResponse,
    AIAssistRequest,
    AIAssistResponse,
    NovelWriteContextRequest,
    NovelWritePreviousContextSummaryRequest,
    NovelPolishRequest,
    NovelWriteRequest,
    VersionCreate,
    VersionResponse,
    VersionCompareResponse,
)
from app.core.exceptions import ChapterNotFoundException

router = APIRouter()

NOVEL_WRITE_MAX_CONTINUATIONS = 2


@router.get("")
async def list_chapters(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    chapters = await chapter_service.get_list(db, project_id)
    return {
        "data": [ChapterResponse.model_validate(c).model_dump() for c in chapters]
    }


@router.get("/{chapter_id}", response_model=ChapterResponse)
async def get_chapter(
    project_id: str,
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    chapter = await chapter_service.get_by_id(db, chapter_id)
    if not chapter:
        raise ChapterNotFoundException()
    return chapter


@router.post("", response_model=ChapterResponse, status_code=201)
async def create_chapter(
    project_id: str,
    data: ChapterCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    chapter = await chapter_service.create(db, project_id, data)
    return chapter


@router.put("/{chapter_id}", response_model=ChapterResponse)
async def update_chapter(
    project_id: str,
    chapter_id: str,
    data: ChapterUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    chapter = await chapter_service.update(db, chapter_id, data)
    if not chapter:
        raise ChapterNotFoundException()
    return chapter


@router.delete("/{chapter_id}", status_code=204)
async def delete_chapter(
    project_id: str,
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    deleted = await chapter_service.delete(db, chapter_id)
    if not deleted:
        raise ChapterNotFoundException()


@router.post("/{chapter_id}/ai-assist", response_model=AIAssistResponse)
async def ai_assist(
    project_id: str,
    chapter_id: str,
    data: AIAssistRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    result = await chapter_service.ai_assist(
        db,
        data.llm_config_id,
        chapter_id,
        data.action,
        data.selection,
        data.context,
    )
    if not result:
        raise ChapterNotFoundException()
    return result


@router.post("/{chapter_id}/ai-stream")
async def ai_stream(
    project_id: str,
    chapter_id: str,
    data: AIAssistRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    async def event_generator():
        async for chunk in chapter_service.ai_stream(
            db,
            data.llm_config_id,
            chapter_id,
            data.action,
            data.selection,
            data.context,
        ):
            yield f"event: chunk\ndata: {json.dumps({'content': chunk})}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_generator(), media_type="text/event-stream"
    )


@router.post("/{chapter_id}/novel-write")
async def novel_write(
    project_id: str,
    chapter_id: str,
    data: NovelWriteRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    result = await chapter_service.novel_write(
        db,
        data.llm_config_id,
        project_id,
        chapter_id,
        data.style_requirements,
        data.write_context,
    )
    if not result:
        raise ChapterNotFoundException()
    return result


@router.post("/{chapter_id}/novel-write-context")
async def novel_write_context(
    project_id: str,
    chapter_id: str,
    data: NovelWriteContextRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    result = await chapter_service.build_novel_write_context(
        db,
        project_id,
        chapter_id,
        data.style_requirements,
    )
    if not result:
        raise ChapterNotFoundException()
    return result


@router.post("/{chapter_id}/novel-write-context/summary")
async def summarize_novel_write_previous_context(
    project_id: str,
    chapter_id: str,
    data: NovelWritePreviousContextSummaryRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    result = await chapter_service.summarize_previous_context(
        db,
        data.llm_config_id,
        project_id,
        chapter_id,
        data.style_requirements,
    )
    if not result:
        raise ChapterNotFoundException()
    return result


@router.post("/{chapter_id}/novel-polish")
async def novel_polish(
    project_id: str,
    chapter_id: str,
    data: NovelPolishRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    result = await chapter_service.novel_polish(
        db,
        data.llm_config_id,
        project_id,
        chapter_id,
        data.polish_suggestions,
        data.chapter_content,
    )
    if not result:
        raise ChapterNotFoundException()
    return result


@router.post("/{chapter_id}/novel-polish-stream")
async def novel_polish_stream(
    project_id: str,
    chapter_id: str,
    data: NovelPolishRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    chapter = await db.get(Chapter, chapter_id)
    if not chapter or chapter.project_id != project_id:
        raise ChapterNotFoundException()

    source_content = (
        data.chapter_content if data.chapter_content is not None else chapter.content or ""
    ).strip()
    prompt_values = await chapter_service.get_novel_polish_prompt_values(db)
    default_suggestions = prompt_values[NOVEL_POLISH_DEFAULT_SUGGESTIONS_KEY]
    messages = chapter_service.build_novel_polish_messages(
        source_content,
        data.polish_suggestions.strip() or default_suggestions,
        prompt_values,
    )
    temperature = await chapter_service.get_novel_polish_temperature(db)
    collected_content = []

    async def event_generator():
        try:
            try:
                async for chunk in llm_orchestrator.stream_chat(
                    data.llm_config_id,
                    messages,
                    temperature=temperature,
                    max_tokens=NOVEL_WRITE_MAX_TOKENS,
                ):
                    if chunk:
                        collected_content.append(chunk)
                        yield (
                            "event: chunk\n"
                            f"data: {json.dumps({'content': chunk})}\n\n"
                        )
                    else:
                        yield "event: ping\ndata: {}\n\n"
            except LLMOutputTruncatedError:
                yield (
                    "event: error\n"
                    f"data: {json.dumps({'error': 'AI 打磨达到模型输出上限，请缩短章节内容或打磨建议后重试'})}\n\n"
                )
                return
            except LLMContentFilteredError:
                yield (
                    "event: error\n"
                    f"data: {json.dumps({'error': 'AI 输出被模型安全策略中断，请调整打磨输入后重试'})}\n\n"
                )
                return

            full_content = "".join(collected_content)
            if not full_content.strip():
                yield (
                    "event: error\n"
                    f"data: {json.dumps({'error': 'AI 打磨未返回正文，请稍后重试'})}\n\n"
                )
                return

            chapter.content = full_content
            cn_chars = len(re.findall(r"[\u4e00-\u9fff]", full_content))
            chapter.word_count = cn_chars
            await db.commit()
            yield (
                "event: done\n"
                f"data: {json.dumps({'word_count': cn_chars})}\n\n"
            )
        except Exception:
            await db.rollback()
            yield (
                "event: error\n"
                f"data: {json.dumps({'error': 'AI 打磨流中断，请稍后重试'})}\n\n"
            )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/{chapter_id}/novel-write-stream")
async def novel_write_stream(
    project_id: str,
    chapter_id: str,
    data: NovelWriteRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise ChapterNotFoundException()

    write_context = await chapter_service.build_novel_write_context(
        db,
        project_id,
        chapter_id,
        data.style_requirements,
        data.write_context,
    )
    prompt_values = await chapter_service.get_novel_write_prompt_values(db)
    messages = chapter_service.build_novel_write_messages(
        write_context, prompt_values
    )
    temperature = await chapter_service.get_novel_write_temperature(db)

    collected_content = []

    async def event_generator():
        try:
            continuation_count = 0
            current_messages = messages
            while True:
                try:
                    async for chunk in llm_orchestrator.stream_chat(
                        data.llm_config_id,
                        current_messages,
                        temperature=temperature,
                        max_tokens=NOVEL_WRITE_MAX_TOKENS,
                    ):
                        if chunk:
                            collected_content.append(chunk)
                            yield (
                                "event: chunk\n"
                                f"data: {json.dumps({'content': chunk})}\n\n"
                            )
                        else:
                            yield "event: ping\ndata: {}\n\n"
                    break
                except LLMOutputTruncatedError:
                    continuation_count += 1
                    full_content = "".join(collected_content)
                    if (
                        continuation_count > NOVEL_WRITE_MAX_CONTINUATIONS
                        or not full_content.strip()
                    ):
                        yield (
                            "event: error\n"
                            f"data: {json.dumps({'error': 'AI 编写达到模型输出上限，请减少 AI 输入长度或降低章节字数后重试'})}\n\n"
                        )
                        return
                    current_messages = (
                        chapter_service.build_novel_write_continuation_messages(
                            write_context, full_content, prompt_values
                        )
                    )
                    yield (
                        "event: status\n"
                        f"data: {json.dumps({'message': 'AI 输出达到长度限制，正在自动续写'})}\n\n"
                    )
                except LLMContentFilteredError:
                    yield (
                        "event: error\n"
                        f"data: {json.dumps({'error': 'AI 输出被模型安全策略中断，请调整 AI 输入后重试'})}\n\n"
                    )
                    return

            full_content = "".join(collected_content)
            if not full_content.strip():
                yield (
                    "event: error\n"
                    f"data: {json.dumps({'error': 'AI 编写未返回正文，请稍后重试'})}\n\n"
                )
                return

            chapter.content = full_content
            cn_chars = len(re.findall(r"[\u4e00-\u9fff]", full_content))
            chapter.word_count = cn_chars
            await db.commit()
            yield (
                "event: done\n"
                f"data: {json.dumps({'word_count': cn_chars})}\n\n"
            )
        except Exception:
            await db.rollback()
            yield (
                "event: error\n"
                f"data: {json.dumps({'error': 'AI 编写流中断，请稍后重试'})}\n\n"
            )

    return StreamingResponse(
        event_generator(), media_type="text/event-stream"
    )


@router.get("/{chapter_id}/versions")
async def list_versions(
    project_id: str,
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    versions = await chapter_service.get_versions(db, chapter_id)
    return {
        "data": [
            VersionResponse.model_validate(v).model_dump() for v in versions
        ]
    }


@router.post("/{chapter_id}/versions", response_model=VersionResponse, status_code=201)
async def create_version(
    project_id: str,
    chapter_id: str,
    data: VersionCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    version = await chapter_service.save_version(db, chapter_id, data)
    if not version:
        raise ChapterNotFoundException()
    return version


@router.get("/{chapter_id}/versions/compare", response_model=VersionCompareResponse)
async def compare_versions(
    project_id: str,
    chapter_id: str,
    v1: int,
    v2: int,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    result = await chapter_service.compare_versions(db, chapter_id, v1, v2)
    if not result:
        raise ChapterNotFoundException()
    return result
