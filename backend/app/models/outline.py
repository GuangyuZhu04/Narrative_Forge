from sqlalchemy import String, Text, Integer, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin


class Outline(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "outlines"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)

    project = relationship("Project", back_populates="outlines")
    nodes = relationship(
        "OutlineNode", back_populates="outline", cascade="all, delete-orphan"
    )


class OutlineNode(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "outline_nodes"

    outline_id: Mapped[str] = mapped_column(
        ForeignKey("outlines.id", ondelete="CASCADE")
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("outline_nodes.id", ondelete="CASCADE")
    )
    node_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON)
    llm_generated: Mapped[bool] = mapped_column(default=False)

    outline = relationship("Outline", back_populates="nodes")
    parent = relationship(
        "OutlineNode", remote_side="OutlineNode.id", back_populates="children"
    )
    children = relationship(
        "OutlineNode", back_populates="parent", cascade="all, delete-orphan"
    )
