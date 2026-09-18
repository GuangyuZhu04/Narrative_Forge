import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, verify_project_access
from app.core.exceptions import ProjectNotFoundException
from app.llm.providers.base import LLMContentFilteredError, LLMOutputTruncatedError
from app.models.agent_session import NovelAgentSession
from app.models.project import Project
from app.schemas.character import CharacterResponse
from app.schemas.chapter import ChapterResponse
from app.schemas.novel_agent import (
    NovelAgentChatTurnRequest,
    NovelAgentContinueRequest,
    NovelAgentExecuteRequest,
    NovelAgentPlanResponse,
    NovelAgentSessionCreate,
    NovelAgentSessionResponse,
    NovelAgentSessionUpdate,
    NovelAgentWriteRequest,
)
from app.schemas.outline import OutlineResponse
from app.schemas.project import ProjectResponse
from app.schemas.scene import SceneResponse
from app.services.novel_agent_continue_service import novel_agent_continue_service
from app.services.novel_agent_chat_service import novel_agent_chat_service
from app.services.novel_agent_service import (
    NovelAgentOutputError,
    novel_agent_service,
)
from app.services.novel_agent_session_service import novel_agent_session_service

logger = logging.getLogger(__name__)
router = APIRouter()
SESSION_MODES = {"generate", "continue_edit", "chat_generate"}


def _serialize_generation_result(result: dict, session_id: str) -> dict:
    return {
        "session_id": session_id,
        "project": ProjectResponse.model_validate(result["project"]).model_dump(
            mode="json"
        ),
        "outline": OutlineResponse.model_validate(result["outline"]).model_dump(
            mode="json"
        ),
        "characters": [
            CharacterResponse.model_validate(item).model_dump(mode="json")
            for item in result["characters"]
        ],
        "scenes": [
            SceneResponse.model_validate(item).model_dump(mode="json")
            for item in result["scenes"]
        ],
        "chapters": [
            ChapterResponse.model_validate(item).model_dump(mode="json")
            for item in result["chapters"]
        ],
        "written_chapters": [
            ChapterResponse.model_validate(item).model_dump(mode="json")
            for item in result["written_chapters"]
        ],
        "blueprint": result["blueprint"],
        "steps": result["steps"],
    }


def _session_response(session: NovelAgentSession) -> dict:
    return NovelAgentSessionResponse.model_validate(session).model_dump(mode="json")


def _sse_data(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _error_message(exc: Exception) -> str:
    if isinstance(exc, NovelAgentOutputError):
        return str(exc)
    if isinstance(exc, LLMOutputTruncatedError):
        return (
            "Agent 输出达到当前模型的长度限制。请减少本步骤的生成数量或内容长度，"
            "再从最近的恢复检查点重试。"
        )
    if isinstance(exc, LLMContentFilteredError):
        return "Agent 输出被模型安全策略中断，请调整输入要求后重试。"
    if isinstance(exc, httpx.HTTPStatusError):
        detail = ""
        try:
            payload = exc.response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                detail = str(error.get("message") or "").strip()
            elif isinstance(error, str):
                detail = error.strip()
            elif isinstance(payload, dict):
                detail = str(payload.get("message") or payload.get("detail") or "").strip()
        except (TypeError, ValueError):
            detail = ""
        status_code = exc.response.status_code
        suffix = f"：{detail[:300]}" if detail else ""
        return f"上游模型 API 返回 HTTP {status_code}{suffix}"
    return "Agent 执行失败，请稍后重试。"


async def _resolve_planning_session(
    db: AsyncSession,
    project_id: str,
    mode: str,
    session_id: str | None,
    request_payload: dict[str, Any],
) -> NovelAgentSession:
    session = await novel_agent_session_service.resolve_session(
        db, project_id, mode, session_id
    )
    if not session:
        raise HTTPException(status_code=404, detail="Agent 会话不存在或模式不匹配")
    return await novel_agent_session_service.start_planning(
        db, session, request_payload
    )


async def _resolve_execution_session(
    db: AsyncSession,
    project_id: str,
    mode: str,
    session_id: str,
) -> NovelAgentSession:
    session = await novel_agent_session_service.get_session(db, session_id)
    if (
        not session
        or session.project_id != project_id
        or session.mode != mode
    ):
        raise HTTPException(status_code=404, detail="Agent 会话不存在或模式不匹配")
    if session.status != "awaiting_confirmation":
        raise HTTPException(
            status_code=409,
            detail="当前 Agent 会话没有等待确认的计划，请先重新生成计划",
        )
    if not isinstance(session.plan, dict) or not isinstance(
        session.request_payload, dict
    ):
        raise HTTPException(status_code=409, detail="Agent 会话缺少可执行计划")
    return await novel_agent_session_service.start_execution(db, session)


@router.get("/sessions")
async def list_agent_sessions(
    project_id: str,
    mode: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    if mode and mode not in SESSION_MODES:
        raise HTTPException(status_code=422, detail="不支持的 Agent 会话模式")
    sessions = await novel_agent_session_service.list_sessions(
        db, project_id, mode
    )
    return {"data": [_session_response(session) for session in sessions]}


@router.post("/sessions", response_model=NovelAgentSessionResponse, status_code=201)
async def create_agent_session(
    project_id: str,
    data: NovelAgentSessionCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    return await novel_agent_session_service.create_session(db, project_id, data)


@router.get("/sessions/{session_id}", response_model=NovelAgentSessionResponse)
async def get_agent_session(
    project_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    session = await novel_agent_session_service.get_session(db, session_id)
    if not session or session.project_id != project_id:
        raise HTTPException(status_code=404, detail="Agent 会话不存在")
    return session


@router.post(
    "/sessions/{session_id}/sync-confirmed-artifacts",
    response_model=NovelAgentSessionResponse,
)
async def sync_confirmed_chat_artifacts(
    project_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    session = await novel_agent_session_service.get_session(db, session_id)
    if (
        not session
        or session.project_id != project_id
        or session.mode != "chat_generate"
    ):
        raise HTTPException(status_code=404, detail="对话创作会话不存在")
    try:
        return await novel_agent_chat_service.sync_session_artifacts(
            db, project_id, session
        )
    except NovelAgentOutputError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/sessions/{session_id}", response_model=NovelAgentSessionResponse)
async def update_agent_session(
    project_id: str,
    session_id: str,
    data: NovelAgentSessionUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    session = await novel_agent_session_service.get_session(db, session_id)
    if not session or session.project_id != project_id:
        raise HTTPException(status_code=404, detail="Agent 会话不存在")
    return await novel_agent_session_service.update_session(db, session, data)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_agent_session(
    project_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    session = await novel_agent_session_service.get_session(db, session_id)
    if not session or session.project_id != project_id:
        raise HTTPException(status_code=404, detail="Agent 会话不存在")
    await novel_agent_session_service.delete_session(db, session)


@router.post("/chat-turn-stream")
async def stream_novel_agent_chat_turn(
    project_id: str,
    data: NovelAgentChatTurnRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    session = await novel_agent_session_service.resolve_session(
        db, project_id, "chat_generate", data.session_id
    )
    if not session:
        raise HTTPException(status_code=404, detail="对话创作会话不存在或模式不匹配")
    session_id = session.id

    async def event_generator():
        try:
            yield _sse_data({"type": "session", "session": _session_response(session)})
            async for event in novel_agent_chat_service.handle_turn_stream(
                db, project_id, session, data
            ):
                yield _sse_data(event)
            refreshed = await novel_agent_session_service.get_session(db, session_id)
            if refreshed:
                yield _sse_data(
                    {"type": "session", "session": _session_response(refreshed)}
                )
            yield _sse_data({"type": "done"})
        except Exception as exc:
            logger.exception(
                "Novel agent chat turn failed for session %s", session_id
            )
            message = _error_message(exc)
            try:
                await db.rollback()
                failed_session = await novel_agent_session_service.get_session(
                    db, session_id
                )
                if failed_session:
                    await novel_agent_session_service.fail_run(
                        db,
                        failed_session,
                        list(failed_session.steps or []),
                        message,
                        result=(
                            failed_session.result
                            if isinstance(failed_session.result, dict)
                            else None
                        ),
                    )
            except Exception:
                logger.exception(
                    "Failed to persist novel agent chat failure for session %s",
                    session_id,
                )
                try:
                    await db.rollback()
                except Exception:
                    logger.exception(
                        "Failed to roll back novel agent chat session %s after "
                        "failure persistence error",
                        session_id,
                    )
            yield _sse_data({"type": "error", "error": message})

    return _streaming_response(event_generator())


@router.post("/write", response_model=NovelAgentPlanResponse)
async def write_novel_from_idea(
    project_id: str,
    data: NovelAgentWriteRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    session = await _resolve_planning_session(
        db,
        project_id,
        "generate",
        data.session_id,
        data.model_dump(mode="json", exclude={"session_id"}),
    )
    steps: list[dict[str, Any]] = []
    blueprint: dict[str, Any] | None = None
    try:
        async for event in novel_agent_service.plan_from_idea_stream(
            db, project_id, data
        ):
            if event["type"] == "steps":
                steps = event["steps"]
            elif event["type"] == "step":
                steps = novel_agent_session_service.merge_step(
                    steps, event["step"]
                )
            elif event["type"] == "plan":
                blueprint = event["plan"]
        if blueprint is None:
            raise ProjectNotFoundException()
        session = await novel_agent_session_service.await_confirmation(
            db, session, blueprint, steps
        )
        return {
            "session_id": session.id,
            "status": "awaiting_confirmation",
            "plan": blueprint,
            "steps": steps,
        }
    except (NovelAgentOutputError, LLMOutputTruncatedError, LLMContentFilteredError) as exc:
        await db.rollback()
        message = _error_message(exc)
        await novel_agent_session_service.fail_run(db, session, [], message)
        raise HTTPException(status_code=400, detail=message) from exc
    except Exception:
        await db.rollback()
        message = "Agent 执行失败，请稍后重试。"
        await novel_agent_session_service.fail_run(db, session, [], message)
        raise


@router.post("/write-stream")
async def stream_novel_from_idea(
    project_id: str,
    data: NovelAgentWriteRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    session = await _resolve_planning_session(
        db,
        project_id,
        "generate",
        data.session_id,
        data.model_dump(mode="json", exclude={"session_id"}),
    )

    async def event_generator():
        steps: list[dict[str, Any]] = []
        blueprint: dict[str, Any] | None = None
        try:
            yield _sse_data({"type": "session", "session": _session_response(session)})
            async for event in novel_agent_service.plan_from_idea_stream(
                db, project_id, data
            ):
                if event["type"] == "steps":
                    steps = event["steps"]
                    yield _sse_data(event)
                elif event["type"] == "step":
                    steps = novel_agent_session_service.merge_step(
                        steps, event["step"]
                    )
                    yield _sse_data(event)
                elif event["type"] == "plan":
                    blueprint = event["plan"]
                    yield _sse_data(event)
            if blueprint is None:
                raise ProjectNotFoundException()
            confirmed_session = (
                await novel_agent_session_service.await_confirmation(
                    db, session, blueprint, steps
                )
            )
            yield _sse_data(
                {
                    "type": "confirmation_required",
                    "session": _session_response(confirmed_session),
                }
            )
            yield _sse_data({"type": "done"})
        except Exception as exc:
            await db.rollback()
            message = _error_message(exc)
            await novel_agent_session_service.fail_run(
                db, session, steps, message
            )
            yield _sse_data({"type": "error", "error": message})

    return _streaming_response(event_generator())


@router.post("/write-execute-stream")
async def stream_execute_novel_plan(
    project_id: str,
    execute_request: NovelAgentExecuteRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    session = await _resolve_execution_session(
        db,
        project_id,
        "generate",
        execute_request.session_id,
    )
    data = NovelAgentWriteRequest.model_validate(
        {**(session.request_payload or {}), "session_id": session.id}
    )
    blueprint = dict(session.plan or {})

    async def event_generator():
        steps: list[dict[str, Any]] = []
        try:
            yield _sse_data({"type": "session", "session": _session_response(session)})
            async for event in novel_agent_service.execute_blueprint_stream(
                db, project_id, data, blueprint
            ):
                if event["type"] == "steps":
                    steps = event["steps"]
                    await novel_agent_session_service.save_progress(
                        db, session, steps
                    )
                    yield _sse_data(event)
                elif event["type"] == "step":
                    steps = novel_agent_session_service.merge_step(
                        steps, event["step"]
                    )
                    await novel_agent_session_service.save_progress(
                        db, session, steps
                    )
                    yield _sse_data(event)
                elif event["type"] == "result":
                    result = event["result"]
                    if not result:
                        raise ProjectNotFoundException()
                    serialized_result = _serialize_generation_result(
                        result, session.id
                    )
                    await novel_agent_session_service.complete_run(
                        db, session, steps, serialized_result
                    )
                    yield _sse_data(
                        {"type": "result", "result": serialized_result}
                    )
            yield _sse_data({"type": "done"})
        except Exception as exc:
            await db.rollback()
            message = _error_message(exc)
            await novel_agent_session_service.fail_run(
                db, session, steps, message
            )
            yield _sse_data({"type": "error", "error": message})

    return _streaming_response(event_generator())


@router.post("/continue-stream")
async def stream_continue_edit(
    project_id: str,
    data: NovelAgentContinueRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    session = await _resolve_planning_session(
        db,
        project_id,
        "continue_edit",
        data.session_id,
        data.model_dump(mode="json", exclude={"session_id"}),
    )

    async def event_generator():
        steps: list[dict[str, Any]] = []
        plan: dict[str, Any] | None = None
        try:
            yield _sse_data({"type": "session", "session": _session_response(session)})
            async for event in novel_agent_continue_service.plan_continue_stream(
                db, project_id, data
            ):
                if event["type"] == "steps":
                    steps = event["steps"]
                    await novel_agent_session_service.save_progress(
                        db, session, steps
                    )
                    yield _sse_data(event)
                elif event["type"] == "step":
                    steps = novel_agent_session_service.merge_step(
                        steps, event["step"]
                    )
                    await novel_agent_session_service.save_progress(
                        db, session, steps
                    )
                    yield _sse_data(event)
                elif event["type"] == "plan":
                    plan = event["plan"]
                    yield _sse_data(event)
            if plan is None:
                raise ProjectNotFoundException()
            confirmed_session = (
                await novel_agent_session_service.await_confirmation(
                    db, session, plan, steps
                )
            )
            yield _sse_data(
                {
                    "type": "confirmation_required",
                    "session": _session_response(confirmed_session),
                }
            )
            yield _sse_data({"type": "done"})
        except Exception as exc:
            await db.rollback()
            message = _error_message(exc)
            await novel_agent_session_service.fail_run(
                db,
                session,
                steps,
                message,
            )
            yield _sse_data({"type": "error", "error": message})

    return _streaming_response(event_generator())


@router.post("/continue-execute-stream")
async def stream_execute_continue_plan(
    project_id: str,
    execute_request: NovelAgentExecuteRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    session = await _resolve_execution_session(
        db,
        project_id,
        "continue_edit",
        execute_request.session_id,
    )
    data = NovelAgentContinueRequest.model_validate(
        {**(session.request_payload or {}), "session_id": session.id}
    )
    plan = dict(session.plan or {})

    async def event_generator():
        steps: list[dict[str, Any]] = []
        action_results: list[dict[str, Any]] = []
        plan_summary = str(plan.get("summary") or "")
        try:
            yield _sse_data({"type": "session", "session": _session_response(session)})
            async for event in (
                novel_agent_continue_service.execute_continue_plan_stream(
                    db,
                    project_id,
                    session.id,
                    data,
                    plan,
                )
            ):
                if event["type"] == "steps":
                    steps = event["steps"]
                    await novel_agent_session_service.save_progress(
                        db, session, steps
                    )
                    yield _sse_data(event)
                elif event["type"] == "step":
                    steps = novel_agent_session_service.merge_step(
                        steps, event["step"]
                    )
                    await novel_agent_session_service.save_progress(
                        db, session, steps
                    )
                    yield _sse_data(event)
                elif event["type"] == "action_result":
                    action_results.append(event["result"])
                    await novel_agent_session_service.save_progress(
                        db,
                        session,
                        steps,
                        {
                            "session_id": session.id,
                            "summary": plan_summary,
                            "actions": action_results,
                        },
                    )
                    yield _sse_data(event)
                elif event["type"] == "result":
                    result = event["result"]
                    if not result:
                        raise ProjectNotFoundException()
                    result = {"session_id": session.id, **result}
                    await novel_agent_session_service.complete_run(
                        db, session, steps, result
                    )
                    yield _sse_data({"type": "result", "result": result})
            yield _sse_data({"type": "done"})
        except Exception as exc:
            await db.rollback()
            message = _error_message(exc)
            partial_result = {
                "session_id": session.id,
                "summary": plan_summary,
                "actions": action_results,
            }
            await novel_agent_session_service.fail_run(
                db,
                session,
                steps,
                message,
                result=partial_result,
            )
            yield _sse_data({"type": "error", "error": message})

    return _streaming_response(event_generator())


def _streaming_response(event_generator) -> StreamingResponse:
    return StreamingResponse(
        event_generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
