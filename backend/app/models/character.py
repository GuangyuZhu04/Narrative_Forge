from sqlalchemy import String, Text, Integer, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin


class Character(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "characters"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    aliases: Mapped[dict | None] = mapped_column(JSON, default=list)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    basic_info: Mapped[dict | None] = mapped_column(JSON)
    personality: Mapped[dict | None] = mapped_column(JSON)
    growth_arc: Mapped[dict | None] = mapped_column(JSON)
    biography: Mapped[str | None] = mapped_column(Text)
    setting_collection: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    project = relationship("Project", back_populates="characters")
    source_relationships = relationship(
        "CharacterRelationship",
        foreign_keys="CharacterRelationship.source_id",
        cascade="all, delete-orphan",
    )
    target_relationships = relationship(
        "CharacterRelationship",
        foreign_keys="CharacterRelationship.target_id",
        cascade="all, delete-orphan",
    )


class CharacterRelationship(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "character_relationships"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE")
    )
    target_id: Mapped[str] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE")
    )
    relationship_type: Mapped[str] = mapped_column(String(30))
    description: Mapped[str | None] = mapped_column(Text)
    intensity: Mapped[int] = mapped_column(Integer, default=5)
    start_chapter: Mapped[str | None] = mapped_column(String(50))
    end_chapter: Mapped[str | None] = mapped_column(String(50))
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON)

    source = relationship("Character", foreign_keys=[source_id], overlaps="source_relationships")
    target = relationship("Character", foreign_keys=[target_id], overlaps="target_relationships")
