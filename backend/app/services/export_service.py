import io
import re
from abc import ABC, abstractmethod

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.chapter import Chapter
from app.models.character import Character

PLATFORM_EXPORT_CONFIG = {
    "fanqie": {
        "platform_name": "番茄小说",
        "target_url": "https://fanqienovel.com/main/writer/book-manage",
    },
    "qidian": {
        "platform_name": "起点作家专区",
        "target_url": "https://write.qq.com/",
    },
}


class BaseExporter(ABC):
    @abstractmethod
    async def export(
        self, db: AsyncSession, project_id: str, options: dict | None = None
    ) -> bytes: ...


class TxtExporter(BaseExporter):
    async def export(
        self, db: AsyncSession, project_id: str, options: dict | None = None
    ) -> bytes:
        project = await db.get(Project, project_id)
        chapters = (
            await db.execute(
                select(Chapter)
                .where(Chapter.project_id == project_id)
                .order_by(Chapter.sort_order)
            )
        ).scalars().all()
        buf = io.StringIO()
        buf.write(f"{project.name}\n{'=' * 40}\n\n")
        if options and options.get("include_outline"):
            buf.write("[大纲]\n\n")
        if options and options.get("include_characters"):
            characters = (
                await db.execute(
                    select(Character).where(
                        Character.project_id == project_id
                    ).order_by(
                        Character.sort_order, Character.created_at, Character.id
                    )
                )
            ).scalars().all()
            buf.write("[人物档案]\n")
            for c in characters:
                buf.write(f"  {c.name}\n")
                if c.biography:
                    buf.write(f"    人物小传：{c.biography}\n")
            buf.write("\n")
        for ch in chapters:
            buf.write(
                f"第{ch.sort_order + 1}章 {ch.title}\n{'-' * 30}\n\n{ch.content or ''}\n\n"
            )
        return buf.getvalue().encode("utf-8")


class MarkdownExporter(BaseExporter):
    async def export(
        self, db: AsyncSession, project_id: str, options: dict | None = None
    ) -> bytes:
        project = await db.get(Project, project_id)
        chapters = (
            await db.execute(
                select(Chapter)
                .where(Chapter.project_id == project_id)
                .order_by(Chapter.sort_order)
            )
        ).scalars().all()
        buf = io.StringIO()
        buf.write(f"# {project.name}\n\n> {project.description or ''}\n\n")
        if options and options.get("include_characters"):
            characters = (
                await db.execute(
                    select(Character).where(
                        Character.project_id == project_id
                    ).order_by(
                        Character.sort_order, Character.created_at, Character.id
                    )
                )
            ).scalars().all()
            buf.write("## 人物档案\n\n")
            for c in characters:
                buf.write(f"- **{c.name}**\n")
                if c.biography:
                    buf.write(f"  - 人物小传：{c.biography}\n")
            buf.write("\n")
        for ch in chapters:
            buf.write(
                f"## 第{ch.sort_order + 1}章 {ch.title}\n\n{ch.content or ''}\n\n"
            )
        return buf.getvalue().encode("utf-8")


class DocxExporter(BaseExporter):
    async def export(
        self, db: AsyncSession, project_id: str, options: dict | None = None
    ) -> bytes:
        from docx import Document

        project = await db.get(Project, project_id)
        chapters = (
            await db.execute(
                select(Chapter)
                .where(Chapter.project_id == project_id)
                .order_by(Chapter.sort_order)
            )
        ).scalars().all()
        doc = Document()
        doc.add_heading(project.name, level=0)
        for ch in chapters:
            doc.add_heading(
                f"第{ch.sort_order + 1}章 {ch.title}", level=1
            )
            for para in (ch.content or "").split("\n"):
                if para.strip():
                    doc.add_paragraph(para)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()


EXPORTER_MAP = {
    "txt": TxtExporter,
    "markdown": MarkdownExporter,
    "docx": DocxExporter,
}


class ExportService:
    async def export_project(
        self,
        db: AsyncSession,
        project_id: str,
        format: str,
        options: dict | None = None,
    ) -> tuple[bytes, str, str]:
        exporter_cls = EXPORTER_MAP.get(format, TxtExporter)
        exporter = exporter_cls()
        content = await exporter.export(db, project_id, options)
        project = await db.get(Project, project_id)

        content_type_map = {
            "txt": "text/plain; charset=utf-8",
            "markdown": "text/markdown; charset=utf-8",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pdf": "application/pdf",
        }
        ext_map = {"txt": ".txt", "markdown": ".md", "docx": ".docx", "pdf": ".pdf"}

        filename = f"{project.name}{ext_map.get(format, '.txt')}"
        content_type = content_type_map.get(format, "text/plain; charset=utf-8")
        return content, filename, content_type

    async def export_platform(
        self,
        db: AsyncSession,
        project_id: str,
        platform: str,
        options: dict | None = None,
    ) -> dict:
        platform_key = platform.lower()
        config = PLATFORM_EXPORT_CONFIG[platform_key]
        project = await db.get(Project, project_id)
        chapters = (
            await db.execute(
                select(Chapter)
                .where(Chapter.project_id == project_id)
                .order_by(Chapter.sort_order, Chapter.created_at, Chapter.id)
            )
        ).scalars().all()

        chapter_items = []
        empty_content_count = 0
        draft_count = 0
        for chapter in chapters:
            content = self._normalize_text(chapter.content or "")
            if not content:
                empty_content_count += 1
            if chapter.status == "draft":
                draft_count += 1

            word_count = chapter.word_count or self._count_visible_chars(content)
            chapter_items.append(
                {
                    "title": self._chapter_title(chapter),
                    "content": content,
                    "word_count": word_count,
                    "sort_order": chapter.sort_order,
                    "status": chapter.status,
                }
            )

        warnings = []
        if not chapter_items:
            warnings.append("当前项目没有可导出的章节")
        if empty_content_count:
            warnings.append(f"{empty_content_count} 个章节暂无正文")
        if draft_count:
            warnings.append(f"{draft_count} 个章节仍为草稿状态")

        clipboard_text = self._build_platform_clipboard_text(
            project,
            chapter_items,
            options or {},
        )
        return {
            "platform": platform_key,
            "platform_name": config["platform_name"],
            "target_url": config["target_url"],
            "project_name": project.name,
            "chapter_count": len(chapter_items),
            "total_word_count": sum(item["word_count"] for item in chapter_items),
            "clipboard_text": clipboard_text,
            "chapters": chapter_items,
            "warnings": warnings,
        }

    def _build_platform_clipboard_text(
        self,
        project: Project,
        chapters: list[dict],
        options: dict,
    ) -> str:
        include_project_header = options.get("include_project_header", True)
        parts = []
        if include_project_header:
            parts.append(f"《{project.name}》")
            description = self._normalize_text(project.description or "")
            if description:
                parts.append(description)

        for chapter in chapters:
            title = chapter["title"]
            content = chapter["content"]
            parts.append(f"{title}\n\n{content}".strip())

        return "\n\n".join(part for part in parts if part)

    @staticmethod
    def _chapter_title(chapter: Chapter) -> str:
        title = (chapter.title or "").strip()
        return title or f"第{chapter.sort_order + 1}章"

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        return "\n".join(line.rstrip() for line in normalized.split("\n"))

    @staticmethod
    def _count_visible_chars(text: str) -> int:
        return len(re.findall(r"\S", text or ""))


export_service = ExportService()
