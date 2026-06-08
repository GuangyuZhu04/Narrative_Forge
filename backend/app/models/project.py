from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin


class Project(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    genre: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    word_count_target: Mapped[int | None] = mapped_column()
    settings: Mapped[str | None] = mapped_column(Text)

    outlines = relationship(
        "Outline", back_populates="project", cascade="all, delete-orphan"
    )
    chapters = relationship(
        "Chapter", back_populates="project", cascade="all, delete-orphan"
    )
    characters = relationship(
        "Character", back_populates="project", cascade="all, delete-orphan"
    )
    analysis_reports = relationship(
        "AnalysisReport", back_populates="project", cascade="all, delete-orphan"
    )
    discussion_sessions = relationship(
        "NovelDiscussionSession",
        back_populates="project",
        cascade="all, delete-orphan",
    )
