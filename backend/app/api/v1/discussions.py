import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, verify_project_access
from app.llm.providers.base import LLMContentFilteredError, LLMOutputTruncatedError
from app.models.project import Project
from app.schemas.discussion import (
    DiscussionMessageResponse,
    DiscussionSendRequest,
    DiscussionSendResponse,
    DiscussionSessionCreate,
    DiscussionSessionDetail,
    DiscussionSessionResponse,
    DiscussionSessionUpdate,
)
from app.services.discussion_service import DISCUSSION_MAX_TOKENS, discussion_service
from app.services.llm_orchestrator import llm_orchestrator
from app.services.system_prompt_service import (
    DISCUSSION_TEMPERATURE_KEY,
    system_prompt_service,
)

router = APIRouter()


def _session_response(session) -> DiscussionSessionResponse:
    return DiscussionSessionResponse.model_validate(session)


@router.get("")
async def list_discussions(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    sessions = await discussion_service.list_sessions(db, project_id)
    return {"data": [_session_response(session).model_dump() for session in sessions]}


@router.post("", response_model=DiscussionSessionResponse, status_code=201)
async def create_discussion(
    project_id: str,
    data: DiscussionSessionCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    return await discussion_service.create_session(db, project_id, data)


@router.get("/{session_id}", response_model=DiscussionSessionDetail)
async def get_discussion(
    project_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    session = await discussion_service.get_session(db, session_id, with_messages=True)
    if not session or session.project_id != project_id:
        raise HTTPException(status_code=404, detail="讨论会话不存在")
    return DiscussionSessionDetail(
        **_session_response(session).model_dump(),
        messages=[
            DiscussionMessageResponse.model_validate(message)
            for message in session.messages
        ],
    )


@router.put("/{session_id}", response_model=DiscussionSessionResponse)
async def update_discussion(
    project_id: str,
    session_id: str,
    data: DiscussionSessionUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    session = await discussion_service.get_session(db, session_id)
    if not session or session.project_id != project_id:
        raise HTTPException(status_code=404, detail="讨论会话不存在")
    updated = await discussion_service.update_session(db, session_id, data)
    return updated


@router.delete("/{session_id}", status_code=204)
async def delete_discussion(
    project_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    session = await discussion_service.get_session(db, session_id)
    if not session or session.project_id != project_id:
        raise HTTPException(status_code=404, detail="讨论会话不存在")
    await discussion_service.delete_session(db, session_id)


@router.post("/{session_id}/messages", response_model=DiscussionSendResponse)
async def send_discussion_message(
    project_id: str,
    session_id: str,
    data: DiscussionSendRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    session = await discussion_service.get_session(db, session_id)
    if not session or session.project_id != project_id:
        raise HTTPException(status_code=404, detail="讨论会话不存在")

    try:
        result = await discussion_service.send_message(db, session_id, data)
    except LLMOutputTruncatedError as exc:
        raise HTTPException(
            status_code=400,
            detail="AI 回复达到模型长度限制，请缩短问题或提高当前 LLM 配置的 max_tokens。",
        ) from exc
    except LLMContentFilteredError as exc:
        raise HTTPException(
            status_code=400,
            detail="AI 回复被模型安全策略中断，请调整讨论内容后重试。",
        ) from exc

    if not result:
        raise HTTPException(status_code=404, detail="讨论会话不存在")
    updated_session, user_message, assistant_message = result
    return DiscussionSendResponse(
        session=_session_response(updated_session),
        user_message=DiscussionMessageResponse.model_validate(user_message),
        assistant_message=DiscussionMessageResponse.model_validate(
            assistant_message
        ),
    )


@router.post("/{session_id}/messages/stream")
async def stream_discussion_message(
    project_id: str,
    session_id: str,
    data: DiscussionSendRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    session = await discussion_service.get_session(db, session_id)
    if not session or session.project_id != project_id:
        raise HTTPException(status_code=404, detail="讨论会话不存在")

    async def event_generator():
        full_content = ""
        try:
            prepared = await discussion_service.prepare_user_message(
                db, session_id, data
            )
            if not prepared:
                yield _sse_data({"type": "error", "error": "讨论会话不存在"})
                return

            current_session, user_message, messages, next_order = prepared
            temperature = data.temperature
            if temperature is None:
                temperature = await system_prompt_service.get_effective_float(
                    db, DISCUSSION_TEMPERATURE_KEY
                )

            async for chunk in llm_orchestrator.stream_chat(
                data.llm_config_id,
                messages,
                temperature=temperature,
                max_tokens=data.max_tokens or DISCUSSION_MAX_TOKENS,
            ):
                if chunk:
                    full_content += chunk
                    yield _sse_data({"type": "chunk", "content": chunk})
                else:
                    yield _sse_data({"type": "ping"})

            assistant_message = await discussion_service.save_assistant_message(
                db, current_session, session_id, full_content, next_order + 1
            )
            await db.refresh(user_message)
            done_payload = {
                "type": "done",
                "session": _session_response(current_session).model_dump(
                    mode="json"
                ),
                "user_message": DiscussionMessageResponse.model_validate(
                    user_message
                ).model_dump(mode="json"),
                "assistant_message": DiscussionMessageResponse.model_validate(
                    assistant_message
                ).model_dump(mode="json"),
            }
            yield _sse_data(done_payload)
        except LLMOutputTruncatedError:
            await db.rollback()
            yield _sse_data(
                {
                    "type": "error",
                    "error": "AI 回复达到模型长度限制，请缩短问题或提高当前 LLM 配置的 max_tokens。",
                }
            )
        except LLMContentFilteredError:
            await db.rollback()
            yield _sse_data(
                {
                    "type": "error",
                    "error": "AI 回复被模型安全策略中断，请调整讨论内容后重试。",
                }
            )
        except Exception:
            await db.rollback()
            yield _sse_data({"type": "error", "error": "AI 回复失败，请稍后重试。"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _sse_data(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
