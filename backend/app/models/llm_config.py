from sqlalchemy import String, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDMixin


class LLMConfig(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "llm_configs"

    provider: Mapped[str] = mapped_column(String(50))
    api_key_encrypted: Mapped[str] = mapped_column(String)
    base_url: Mapped[str] = mapped_column(String(500))
    model_name: Mapped[str] = mapped_column(String(100))
    default_params: Mapped[dict] = mapped_column(JSON, default=dict)
    rate_limit: Mapped[dict | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
