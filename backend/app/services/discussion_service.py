from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.discussion import NovelDiscussionMessage, NovelDiscussionSession
from app.schemas.discussion import (
    DiscussionSendRequest,
    DiscussionSessionCreate,
    DiscussionSessionUpdate,
)
from app.services.llm_orchestrator import llm_orchestrator
from app.services.system_prompt_service import (
    DISCUSSION_TEMPERATURE_KEY,
    system_prompt_service,
)

DEFAULT_DISCUSSION_SYSTEM_PROMPT = """你是一位专业的中文长篇小说创作顾问。
你需要和作者进行多轮讨论，帮助作者梳理故事设定、人物动机、情节推进、章节安排、冲突升级和伏笔回收。
回答应当具体、可落地，尽量给出可直接导入小说项目的内容。"""

DISCUSSION_MAX_TOKENS = 32768


class DiscussionService:
    async def list_sessions(
        self, db: AsyncSession, project_id: str
    ) -> list[NovelDiscussionSession]:
        result = await db.execute(
            select(NovelDiscussionSession)
            .where(NovelDiscussionSession.project_id == project_id)
            .order_by(
                NovelDiscussionSession.updated_at.desc(),
                NovelDiscussionSession.created_at.desc(),
            )
        )
        return list(result.scalars().all())

    async def get_session(
        self,
        db: AsyncSession,
        session_id: str,
        with_messages: bool = False,
    ) -> NovelDiscussionSession | None:
        statement = select(NovelDiscussionSession).where(
            NovelDiscussionSession.id == session_id
        )
        if with_messages:
            statement = statement.options(
                selectinload(NovelDiscussionSession.messages)
            )
        result = await db.execute(statement)
        session = result.scalar_one_or_none()
        if session and with_messages:
            session.messages.sort(key=lambda item: item.sort_order)
        return session

    async def create_session(
        self,
        db: AsyncSession,
        project_id: str,
        data: DiscussionSessionCreate,
    ) -> NovelDiscussionSession:
        session = NovelDiscussionSession(
            project_id=project_id,
            title=(data.title or "新的小说讨论").strip() or "新的小说讨论",
            system_prompt=data.system_prompt or DEFAULT_DISCUSSION_SYSTEM_PROMPT,
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def update_session(
        self,
        db: AsyncSession,
        session_id: str,
        data: DiscussionSessionUpdate,
    ) -> NovelDiscussionSession | None:
        session = await db.get(NovelDiscussionSession, session_id)
        if not session:
            return None
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if key == "title" and isinstance(value, str):
                value = value.strip() or session.title
            setattr(session, key, value)
        await db.commit()
        await db.refresh(session)
        return session

    async def delete_session(self, db: AsyncSession, session_id: str) -> bool:
        session = await db.get(NovelDiscussionSession, session_id)
        if not session:
            return False
        await db.delete(session)
        await db.commit()
        return True

    async def send_message(
        self,
        db: AsyncSession,
        session_id: str,
        data: DiscussionSendRequest,
    ) -> tuple[
        NovelDiscussionSession,
        NovelDiscussionMessage,
        NovelDiscussionMessage,
    ] | None:
        prepared = await self.prepare_user_message(db, session_id, data)
        if not prepared:
            return None
        session, user_message, messages, next_order = prepared
        temperature = data.temperature
        if temperature is None:
            temperature = await system_prompt_service.get_effective_float(
                db, DISCUSSION_TEMPERATURE_KEY
            )
        response = await llm_orchestrator.chat(
            data.llm_config_id,
            messages,
            temperature=temperature,
            max_tokens=data.max_tokens or DISCUSSION_MAX_TOKENS,
        )
        assistant_message = await self.save_assistant_message(
            db, session, session_id, response, next_order + 1
        )
        await db.refresh(user_message)
        return session, user_message, assistant_message

    async def prepare_user_message(
        self,
        db: AsyncSession,
        session_id: str,
        data: DiscussionSendRequest,
    ) -> tuple[
        NovelDiscussionSession,
        NovelDiscussionMessage,
        list[dict[str, str]],
        int,
    ] | None:
        session = await self.get_session(db, session_id, with_messages=True)
        if not session:
            return None

        next_order = await self._get_next_message_order(db, session_id)
        user_message = NovelDiscussionMessage(
            session_id=session_id,
            role="user",
            content=data.content.strip(),
            sort_order=next_order,
        )
        db.add(user_message)
        await db.flush()
        messages = self._build_llm_messages(session, user_message)
        return session, user_message, messages, next_order

    async def save_assistant_message(
        self,
        db: AsyncSession,
        session: NovelDiscussionSession,
        session_id: str,
        content: str,
        sort_order: int,
    ) -> NovelDiscussionMessage:
        assistant_message = NovelDiscussionMessage(
            session_id=session_id,
            role="assistant",
            content=content,
            sort_order=sort_order,
        )
        db.add(assistant_message)
        session.updated_at = datetime.now(UTC).replace(tzinfo=None)
        await db.commit()
        await db.refresh(session)
        await db.refresh(assistant_message)
        return assistant_message

    async def _get_next_message_order(
        self, db: AsyncSession, session_id: str
    ) -> int:
        result = await db.execute(
            select(func.max(NovelDiscussionMessage.sort_order)).where(
                NovelDiscussionMessage.session_id == session_id
            )
        )
        max_order = result.scalar()
        return (max_order if max_order is not None else -1) + 1

    def _build_llm_messages(
        self,
        session: NovelDiscussionSession,
        user_message: NovelDiscussionMessage,
    ) -> list[dict[str, str]]:
        messages = [
            {
                "role": "system",
                "content": session.system_prompt or DEFAULT_DISCUSSION_SYSTEM_PROMPT,
            }
        ]
        existing_messages = sorted(session.messages, key=lambda item: item.sort_order)
        for message in existing_messages:
            if message.role in {"user", "assistant"}:
                messages.append({"role": message.role, "content": message.content})
        messages.append({"role": "user", "content": user_message.content})
        return messages


discussion_service = DiscussionService()
