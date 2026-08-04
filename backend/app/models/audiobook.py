from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin


class AudiobookConfig(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "audiobook_configs"
    __table_args__ = (UniqueConstraint("project_id", name="uq_audiobook_config_project"),)

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(30), default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String(500), default="http://127.0.0.1:8001/v1")
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(200), default="tts-1")
    narrator_voice: Mapped[str] = mapped_column(String(200), default="alloy")
    character_voices: Mapped[dict] = mapped_column(JSON, default=dict)
    managed_voices: Mapped[list] = mapped_column(JSON, default=list)
    deleted_voice_ids: Mapped[list] = mapped_column(JSON, default=list)
    speed: Mapped[float] = mapped_column(Float, default=1.0)
    use_ffmpeg: Mapped[bool] = mapped_column(Boolean, default=True)
    max_chars_per_segment: Mapped[int] = mapped_column(Integer, default=800)
    request_timeout_seconds: Mapped[int] = mapped_column(Integer, default=180)
    requests_per_minute: Mapped[int] = mapped_column(Integer, default=20)
    comfyui_workflow: Mapped[dict | None] = mapped_column(JSON)
    custom_request: Mapped[dict | None] = mapped_column(JSON)

    project = relationship("Project", back_populates="audiobook_config")
    jobs = relationship("AudiobookJob", back_populates="config")


class AudiobookJob(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "audiobook_jobs"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    config_id: Mapped[str | None] = mapped_column(
        ForeignKey("audiobook_configs.id", ondelete="SET NULL")
    )
    script_llm_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("llm_configs.id", ondelete="SET NULL")
    )
    scope_type: Mapped[str] = mapped_column(String(20))
    scope_id: Mapped[str | None] = mapped_column(String(100))
    scope_title: Mapped[str] = mapped_column(String(300))
    chapter_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    processed_chapters: Mapped[int] = mapped_column(Integer, default=0)
    total_chapters: Mapped[int] = mapped_column(Integer, default=0)
    current_chapter_title: Mapped[str | None] = mapped_column(String(300))
    speech_scripts: Mapped[dict] = mapped_column(JSON, default=dict)
    segment_tasks: Mapped[list] = mapped_column(JSON, default=list)
    output_files: Mapped[list] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    project = relationship("Project", back_populates="audiobook_jobs")
    config = relationship("AudiobookConfig", back_populates="jobs")
