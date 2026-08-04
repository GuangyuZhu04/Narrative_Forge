from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_session import NovelAgentSession
from app.schemas.novel_agent import (
    NovelAgentSessionCreate,
    NovelAgentSessionUpdate,
)


class NovelAgentSessionService:
    async def list_sessions(
        self,
        db: AsyncSession,
        project_id: str,
        mode: str | None = None,
    ) -> list[NovelAgentSession]:
        statement = select(NovelAgentSession).where(
            NovelAgentSession.project_id == project_id
        )
        if mode:
            statement = statement.where(NovelAgentSession.mode == mode)
        result = await db.execute(
            statement.order_by(
                NovelAgentSession.updated_at.desc(),
                NovelAgentSession.created_at.desc(),
            )
        )
        return list(result.scalars().all())

    async def get_session(
        self,
        db: AsyncSession,
        session_id: str,
    ) -> NovelAgentSession | None:
        return await db.get(NovelAgentSession, session_id)

    async def create_session(
        self,
        db: AsyncSession,
        project_id: str,
        data: NovelAgentSessionCreate,
    ) -> NovelAgentSession:
        session = NovelAgentSession(
            project_id=project_id,
            mode=data.mode,
            name="",
            status="idle",
            request_payload=None,
            plan=None,
            result=None,
            steps=[],
            error_message=None,
        )
        db.add(session)
        await db.flush()
        session.name = (data.name or "").strip() or session.id
        await db.commit()
        await db.refresh(session)
        return session

    async def resolve_session(
        self,
        db: AsyncSession,
        project_id: str,
        mode: str,
        session_id: str | None,
    ) -> NovelAgentSession | None:
        if not session_id:
            return await self.create_session(
                db,
                project_id,
                NovelAgentSessionCreate(mode=mode),
            )
        session = await self.get_session(db, session_id)
        if (
            not session
            or session.project_id != project_id
            or session.mode != mode
        ):
            return None
        return session

    async def update_session(
        self,
        db: AsyncSession,
        session: NovelAgentSession,
        data: NovelAgentSessionUpdate,
    ) -> NovelAgentSession:
        session.name = data.name.strip()
        self._touch(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def delete_session(
        self,
        db: AsyncSession,
        session: NovelAgentSession,
    ) -> None:
        await db.delete(session)
        await db.commit()

    async def start_planning(
        self,
        db: AsyncSession,
        session: NovelAgentSession,
        request_payload: dict[str, Any],
    ) -> NovelAgentSession:
        session.status = "planning"
        session.request_payload = deepcopy(request_payload)
        session.plan = None
        session.result = None
        session.steps = []
        session.error_message = None
        self._touch(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def await_confirmation(
        self,
        db: AsyncSession,
        session: NovelAgentSession,
        plan: dict[str, Any],
        steps: list[dict[str, Any]],
    ) -> NovelAgentSession:
        session.status = "awaiting_confirmation"
        session.plan = deepcopy(plan)
        session.result = None
        session.steps = deepcopy(steps)
        session.error_message = None
        self._touch(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def start_execution(
        self,
        db: AsyncSession,
        session: NovelAgentSession,
    ) -> NovelAgentSession:
        session.status = "running"
        session.result = None
        session.error_message = None
        self._touch(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def start_run(
        self,
        db: AsyncSession,
        session: NovelAgentSession,
        request_payload: dict[str, Any],
    ) -> NovelAgentSession:
        """Backward-compatible alias for callers that start a planning phase."""
        return await self.start_planning(db, session, request_payload)

    async def save_plan(
        self,
        db: AsyncSession,
        session: NovelAgentSession,
        plan: dict[str, Any],
    ) -> None:
        session.plan = deepcopy(plan)
        self._touch(session)
        await db.commit()

    async def save_progress(
        self,
        db: AsyncSession,
        session: NovelAgentSession,
        steps: list[dict[str, Any]],
        result: dict[str, Any] | None = None,
    ) -> None:
        session.steps = deepcopy(steps)
        if result is not None:
            session.result = deepcopy(result)
        self._touch(session)
        await db.commit()

    async def complete_run(
        self,
        db: AsyncSession,
        session: NovelAgentSession,
        steps: list[dict[str, Any]],
        result: dict[str, Any],
    ) -> None:
        session.status = "completed"
        session.steps = deepcopy(steps)
        session.result = deepcopy(result)
        session.error_message = None
        self._touch(session)
        await db.commit()

    async def fail_run(
        self,
        db: AsyncSession,
        session: NovelAgentSession,
        steps: list[dict[str, Any]],
        error_message: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        session.status = "failed"
        session.steps = deepcopy(steps)
        if result is not None:
            session.result = deepcopy(result)
        session.error_message = error_message
        self._touch(session)
        await db.commit()

    @staticmethod
    def merge_step(
        steps: list[dict[str, Any]],
        next_step: dict[str, Any],
    ) -> list[dict[str, Any]]:
        merged = [dict(step) for step in steps]
        for index, step in enumerate(merged):
            if step.get("step") == next_step.get("step"):
                merged[index] = dict(next_step)
                return merged
        merged.append(dict(next_step))
        return merged

    @staticmethod
    def _touch(session: NovelAgentSession) -> None:
        session.updated_at = datetime.now(UTC).replace(tzinfo=None)


novel_agent_session_service = NovelAgentSessionService()
