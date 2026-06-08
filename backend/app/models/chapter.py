from sqlalchemy import String, Text, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin


class Chapter(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "chapters"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    outline_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("outline_nodes.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    word_count: Mapped[int] = mapped_column(Integer, default=0)

    project = relationship("Project", back_populates="chapters")
    versions = relationship(
        "ChapterVersion", back_populates="chapter", cascade="all, delete-orphan"
    )


class ChapterVersion(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "chapter_versions"

    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer)
    change_summary: Mapped[str | None] = mapped_column(Text)

    chapter = relationship("Chapter", back_populates="versions")
