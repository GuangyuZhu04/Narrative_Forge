from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin


class NovelDiscussionSession(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "novel_discussion_sessions"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(200))
    system_prompt: Mapped[str | None] = mapped_column(Text)

    project = relationship("Project", back_populates="discussion_sessions")
    messages = relationship(
        "NovelDiscussionMessage",
        back_populates="session",
        cascade="all, delete-orphan",
    )


class NovelDiscussionMessage(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "novel_discussion_messages"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("novel_discussion_sessions.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    session = relationship("NovelDiscussionSession", back_populates="messages")
