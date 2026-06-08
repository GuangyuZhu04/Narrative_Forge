import asyncio
import json
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.llm.prompts.consistency import (
    CONSISTENCY_CHARACTER_PERSONALITY_SYSTEM,
    CONSISTENCY_CHARACTER_PERSONALITY_USER,
    CONSISTENCY_CONTENT_CONSISTENCY_SYSTEM,
    CONSISTENCY_CONTENT_CONSISTENCY_USER,
    CONSISTENCY_PLOT_CONSISTENCY_SYSTEM,
    CONSISTENCY_PLOT_CONSISTENCY_USER,
    CONSISTENCY_PLOT_CONTINUITY_SYSTEM,
    CONSISTENCY_PLOT_CONTINUITY_USER,
)
from app.models.analysis import AnalysisReport
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.outline import Outline, OutlineNode
from app.services.llm_orchestrator import llm_orchestrator
from app.services.system_prompt_service import (
    CONSISTENCY_ANALYSIS_TEMPERATURE_KEY,
    system_prompt_service,
)


DEFAULT_CONSISTENCY_DIMENSIONS = [
    "character_personality",
    "plot_consistency",
    "plot_continuity",
    "content_consistency",
]

DIMENSION_ALIASES = {
    "character": "character_personality",
    "plot": "plot_consistency",
    "timeline": "plot_continuity",
    "setting": "content_consistency",
    "logic": "content_consistency",
}

DIMENSION_PROMPTS = {
    "character_personality": (
        CONSISTENCY_CHARACTER_PERSONALITY_SYSTEM,
        CONSISTENCY_CHARACTER_PERSONALITY_USER,
    ),
    "plot_consistency": (
        CONSISTENCY_PLOT_CONSISTENCY_SYSTEM,
        CONSISTENCY_PLOT_CONSISTENCY_USER,
    ),
    "plot_continuity": (
        CONSISTENCY_PLOT_CONTINUITY_SYSTEM,
        CONSISTENCY_PLOT_CONTINUITY_USER,
    ),
    "content_consistency": (
        CONSISTENCY_CONTENT_CONSISTENCY_SYSTEM,
        CONSISTENCY_CONTENT_CONSISTENCY_USER,
    ),
}


class ConsistencyService:
    async def analyze_chapter(
        self,
        db: AsyncSession,
        project_id: str,
        chapter_id: str,
        llm_config_id: str,
        dimensions: list[str] | None = None,
    ) -> dict | None:
        chapter = await self.get_active_chapter(db, project_id, chapter_id)
        if not chapter:
            return None

        normalized_dimensions = self.normalize_dimensions(dimensions)
        characters = await self.get_project_characters(db, project_id)
        context = await self._assemble_context(db, project_id, chapter)
        context["character_profiles"] = self.format_character_profiles(characters)
        temperature = await system_prompt_service.get_effective_float(
            db, CONSISTENCY_ANALYSIS_TEMPERATURE_KEY
        )

        tasks = [
            self._analyze_dimension(llm_config_id, dim, context, temperature)
            for dim in normalized_dimensions
        ]
        task_results = await asyncio.gather(*tasks, return_exceptions=True)

        results = {}
        for dim, result in zip(normalized_dimensions, task_results):
            if isinstance(result, Exception):
                results[dim] = {"issues": [], "suggestions": [], "score": None}
            else:
                results[dim] = result

        existing_reports = list(
            (
                await db.execute(
                    select(AnalysisReport)
                    .where(AnalysisReport.project_id == project_id)
                    .where(AnalysisReport.chapter_id == chapter_id)
                    .where(AnalysisReport.analysis_type.in_(results.keys()))
                )
            )
            .scalars()
            .all()
        )
        for report in existing_reports:
            await db.delete(report)

        for dim, result in results.items():
            db.add(
                AnalysisReport(
                    project_id=project_id,
                    chapter_id=chapter_id,
                    analysis_type=dim,
                    status="completed",
                    issues=result.get("issues", []),
                    suggestions=result.get("suggestions", []),
                    score=result.get("score"),
                )
            )
        await db.commit()

        return results

    def normalize_dimensions(self, dimensions: list[str] | None = None) -> list[str]:
        requested = dimensions or DEFAULT_CONSISTENCY_DIMENSIONS
        normalized = []
        for dim in requested:
            canonical = DIMENSION_ALIASES.get(dim, dim)
            if canonical in DIMENSION_PROMPTS and canonical not in normalized:
                normalized.append(canonical)
        return normalized or DEFAULT_CONSISTENCY_DIMENSIONS

    async def get_active_chapter(
        self, db: AsyncSession, project_id: str, chapter_id: str
    ) -> Chapter | None:
        return (
            await db.execute(
                select(Chapter)
                .join(OutlineNode, Chapter.outline_node_id == OutlineNode.id)
                .join(Outline, OutlineNode.outline_id == Outline.id)
                .where(Chapter.id == chapter_id)
                .where(Chapter.project_id == project_id)
                .where(Outline.project_id == project_id)
                .where(OutlineNode.node_type == "CHAPTER")
            )
        ).scalar_one_or_none()

    async def get_active_chapter_options(
        self, db: AsyncSession, project_id: str
    ) -> list[dict]:
        parent = aliased(OutlineNode)
        rows = (
            await db.execute(
                select(Chapter, OutlineNode, parent.title, parent.sort_order)
                .join(OutlineNode, Chapter.outline_node_id == OutlineNode.id)
                .join(Outline, OutlineNode.outline_id == Outline.id)
                .outerjoin(parent, OutlineNode.parent_id == parent.id)
                .where(Chapter.project_id == project_id)
                .where(Outline.project_id == project_id)
                .where(OutlineNode.node_type == "CHAPTER")
                .order_by(parent.sort_order, OutlineNode.sort_order, Chapter.sort_order)
            )
        ).all()
        return [
            {
                "id": chapter.id,
                "outline_node_id": node.id,
                "title": node.title or chapter.title,
                "summary": node.summary or chapter.summary,
                "volume_title": volume_title,
                "sort_order": node.sort_order,
            }
            for chapter, node, volume_title, _volume_order in rows
        ]

    async def _assemble_context(
        self, db: AsyncSession, project_id: str, chapter: Chapter
    ) -> dict:
        chapter_info = await self._get_chapter_info(db, chapter)
        previous_sources = await self._get_neighbor_sources(
            db, project_id, chapter, before=True, limit=3
        )
        next_sources = await self._get_neighbor_sources(
            db, project_id, chapter, before=False, limit=1
        )
        return {
            "chapter_content": chapter.content or "",
            "chapter_title": chapter_info["title"],
            "chapter_summary": chapter_info["summary"] or "暂无章节摘要",
            "previous_summary": self._format_sources(previous_sources),
            "previous_chapter_context": self._format_single_source(
                previous_sources[-1] if previous_sources else None
            ),
            "next_chapter_context": self._format_single_source(
                next_sources[0] if next_sources else None
            ),
        }

    async def _get_chapter_info(self, db: AsyncSession, chapter: Chapter) -> dict:
        node = await self._get_active_outline_node(db, chapter)
        if node:
            return {
                "title": node.title or chapter.title or "未命名章节",
                "summary": node.summary or chapter.summary or "",
                "node": node,
            }
        return {
            "title": chapter.title or "未命名章节",
            "summary": chapter.summary or "",
            "node": None,
        }

    async def _get_active_outline_node(
        self, db: AsyncSession, chapter: Chapter
    ) -> OutlineNode | None:
        if not chapter.outline_node_id:
            return None
        return (
            await db.execute(
                select(OutlineNode)
                .join(Outline, OutlineNode.outline_id == Outline.id)
                .where(OutlineNode.id == chapter.outline_node_id)
                .where(Outline.project_id == chapter.project_id)
                .where(OutlineNode.node_type == "CHAPTER")
            )
        ).scalar_one_or_none()

    async def _get_neighbor_sources(
        self,
        db: AsyncSession,
        project_id: str,
        chapter: Chapter,
        before: bool,
        limit: int,
    ) -> list[dict[str, str]]:
        parent = aliased(OutlineNode)
        rows = list(
            (
                await db.execute(
                    select(Chapter, OutlineNode)
                    .join(OutlineNode, Chapter.outline_node_id == OutlineNode.id)
                    .join(Outline, OutlineNode.outline_id == Outline.id)
                    .outerjoin(parent, OutlineNode.parent_id == parent.id)
                    .where(Chapter.project_id == project_id)
                    .where(Outline.project_id == project_id)
                    .where(OutlineNode.node_type == "CHAPTER")
                    .order_by(
                        parent.sort_order,
                        OutlineNode.sort_order,
                        Chapter.sort_order,
                        Chapter.created_at,
                        Chapter.id,
                    )
                )
            ).all()
        )
        current_index = next(
            (
                index
                for index, (candidate_chapter, _node) in enumerate(rows)
                if candidate_chapter.id == chapter.id
            ),
            None,
        )
        if current_index is not None:
            if before:
                neighbors = rows[max(0, current_index - limit) : current_index]
            else:
                neighbors = rows[current_index + 1 : current_index + 1 + limit]
            return [
                self._build_chapter_source(neighbor_chapter, node)
                for neighbor_chapter, node in neighbors
            ]

        chapter_query = (
            select(Chapter)
            .where(Chapter.project_id == project_id)
            .where(
                Chapter.sort_order < chapter.sort_order
                if before
                else Chapter.sort_order > chapter.sort_order
            )
            .order_by(Chapter.sort_order.desc() if before else Chapter.sort_order.asc())
            .limit(limit)
        )
        neighbors = list((await db.execute(chapter_query)).scalars().all())
        if before:
            neighbors.reverse()
        return [self._build_chapter_source(item, None) for item in neighbors]

    def _build_chapter_source(
        self, chapter: Chapter | None, node: OutlineNode | None
    ) -> dict[str, str]:
        title = node.title if node else None
        summary = node.summary if node else None
        if chapter:
            title = title or chapter.title
            summary = summary or chapter.summary
        return {
            "title": title or "未命名章节",
            "summary": (summary or "").strip(),
            "content": ((chapter.content if chapter else "") or "").strip()[:3000],
        }

    def _format_sources(self, sources: list[dict[str, str]]) -> str:
        if not sources:
            return "暂无前文信息"
        return "\n\n".join(self._format_single_source(source) for source in sources)

    def _format_single_source(self, source: dict[str, str] | None) -> str:
        if not source:
            return "暂无相邻章节信息"
        parts = [f"标题：{source['title']}"]
        if source["summary"]:
            parts.append(f"摘要：{source['summary']}")
        if source["content"]:
            parts.append(f"内容摘录：{source['content']}")
        return "\n".join(parts)

    async def get_report_chapter_title(
        self, db: AsyncSession, report: AnalysisReport
    ) -> str | None:
        if not report.chapter_id:
            return None
        chapter = await self.get_active_chapter(db, report.project_id, report.chapter_id)
        if not chapter:
            return None
        return (await self._get_chapter_info(db, chapter))["title"]

    async def get_project_characters(
        self, db: AsyncSession, project_id: str
    ) -> list[Character]:
        return list(
            (
                await db.execute(
                    select(Character)
                    .where(Character.project_id == project_id)
                    .order_by(Character.sort_order, Character.created_at, Character.id)
                )
            )
            .scalars()
            .all()
        )

    def format_character_profiles(self, characters: list[Character]) -> str:
        if not characters:
            return "暂无人物定义"
        return "\n\n".join(
            (
                f"姓名：{c.name}\n"
                f"性格：{c.personality if c.personality else '暂无'}\n"
                f"人物小传：{c.biography or '暂无'}"
            )
            for c in characters
        )

    async def _analyze_dimension(
        self, llm_config_id: str, dimension: str, context: dict, temperature: float
    ) -> dict:
        system, user_template = DIMENSION_PROMPTS[dimension]
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_template.format(**context)},
        ]
        response = await llm_orchestrator.chat(
            llm_config_id, messages, temperature=temperature
        )
        return json.loads(response)

    async def stream_analyze(
        self,
        db: AsyncSession,
        llm_config_id: str,
        context: dict,
        dimension: str,
    ) -> AsyncIterator[str]:
        canonical = self.normalize_dimensions([dimension])[0]
        system, user_template = DIMENSION_PROMPTS[canonical]
        user = user_template.format(**context)
        temperature = await system_prompt_service.get_effective_float(
            db, CONSISTENCY_ANALYSIS_TEMPERATURE_KEY
        )

        async for chunk in llm_orchestrator.stream_chat(
            llm_config_id,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
        ):
            yield chunk

    async def get_reports(
        self,
        db: AsyncSession,
        project_id: str,
        chapter_id: str | None = None,
        analysis_type: str | None = None,
    ) -> list[AnalysisReport]:
        query = (
            select(AnalysisReport)
            .join(Chapter, AnalysisReport.chapter_id == Chapter.id)
            .join(OutlineNode, Chapter.outline_node_id == OutlineNode.id)
            .join(Outline, OutlineNode.outline_id == Outline.id)
            .where(AnalysisReport.project_id == project_id)
            .where(Chapter.project_id == project_id)
            .where(Outline.project_id == project_id)
            .where(OutlineNode.node_type == "CHAPTER")
        )
        if chapter_id:
            query = query.where(AnalysisReport.chapter_id == chapter_id)
        if analysis_type:
            query = query.where(
                AnalysisReport.analysis_type
                == DIMENSION_ALIASES.get(analysis_type, analysis_type)
            )
        result = await db.execute(query.order_by(AnalysisReport.created_at.desc()))
        reports = list(result.scalars().all())
        latest_reports = []
        seen = set()
        for report in reports:
            key = (report.chapter_id, report.analysis_type)
            if key in seen:
                continue
            seen.add(key)
            latest_reports.append(report)
        return latest_reports

    async def get_report(
        self, db: AsyncSession, report_id: str
    ) -> AnalysisReport | None:
        return await db.get(AnalysisReport, report_id)


consistency_service = ConsistencyService()
