import difflib
import re
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter, ChapterVersion
from app.models.character import Character
from app.models.outline import Outline, OutlineNode
from app.models.scene import Scene
from app.schemas.chapter import (
    ChapterCreate,
    ChapterUpdate,
    NovelWriteContextOverride,
    VersionCreate,
)
from app.services.llm_orchestrator import llm_orchestrator
from app.llm.prompts.chapter import (
    CHAPTER_CONTINUE_SYSTEM,
    CHAPTER_CONTINUE_USER,
    CHAPTER_REWRITE_SYSTEM,
    CHAPTER_REWRITE_USER,
    CHAPTER_POLISH_SYSTEM,
    CHAPTER_POLISH_USER,
    CHAPTER_EXPAND_SYSTEM,
    CHAPTER_EXPAND_USER,
    CHAPTER_SUMMARIZE_SYSTEM,
    CHAPTER_SUMMARIZE_USER,
    CHAPTER_DIALOGUE_SYSTEM,
    CHAPTER_DIALOGUE_USER,
)
from app.llm.prompts.novel_write import (
    NOVEL_DEFAULT_STYLE_REQUIREMENTS,
    NOVEL_WRITE_CONTINUATION_USER,
    NOVEL_WRITE_SYSTEM,
    NOVEL_WRITE_USER,
)
from app.llm.prompts.novel_polish import (
    NOVEL_POLISH_SYSTEM,
    NOVEL_POLISH_USER,
)
from app.services.system_prompt_service import (
    CHAPTER_CONTINUE_TEMPERATURE_KEY,
    CHAPTER_DIALOGUE_TEMPERATURE_KEY,
    CHAPTER_EXPAND_TEMPERATURE_KEY,
    CHAPTER_POLISH_TEMPERATURE_KEY,
    CHAPTER_REWRITE_TEMPERATURE_KEY,
    CHAPTER_SUMMARIZE_TEMPERATURE_KEY,
    NOVEL_POLISH_DEFAULT_SUGGESTIONS_KEY,
    NOVEL_POLISH_SYSTEM_KEY,
    NOVEL_POLISH_TEMPERATURE_KEY,
    NOVEL_POLISH_USER_TEMPLATE_KEY,
    NOVEL_WRITE_CONTINUATION_USER_KEY,
    NOVEL_WRITE_DEFAULT_STYLE_KEY,
    NOVEL_WRITE_PREVIOUS_SUMMARY_SYSTEM_KEY,
    NOVEL_WRITE_PREVIOUS_SUMMARY_TEMPERATURE_KEY,
    NOVEL_WRITE_PREVIOUS_SUMMARY_USER_KEY,
    NOVEL_WRITE_SYSTEM_KEY,
    NOVEL_WRITE_TEMPERATURE_KEY,
    NOVEL_WRITE_USER_TEMPLATE_KEY,
    system_prompt_service,
)


DEFAULT_NOVEL_STYLE_REQUIREMENTS = NOVEL_DEFAULT_STYLE_REQUIREMENTS
PREVIOUS_CONTEXT_EXCERPT_LIMIT = 1200
PREVIOUS_CONTEXT_SUMMARY_SOURCE_LIMIT = 3000
PREVIOUS_CONTEXT_SUMMARY_TOTAL_LIMIT = 30000
PREVIOUS_CHAPTER_CONTENT_LIMIT = 6000
NOVEL_WRITE_CONTINUATION_CONTEXT_LIMIT = 12000
NOVEL_WRITE_MAX_TOKENS = 8192*2


class ChapterService:
    async def get_novel_write_prompt_values(self, db: AsyncSession) -> dict[str, str]:
        return await system_prompt_service.get_effective_values(
            db,
            [
                NOVEL_WRITE_SYSTEM_KEY,
                NOVEL_WRITE_USER_TEMPLATE_KEY,
                NOVEL_WRITE_CONTINUATION_USER_KEY,
            ],
        )

    async def get_novel_previous_summary_prompt_values(
        self, db: AsyncSession
    ) -> dict[str, str]:
        return await system_prompt_service.get_effective_values(
            db,
            [
                NOVEL_WRITE_PREVIOUS_SUMMARY_SYSTEM_KEY,
                NOVEL_WRITE_PREVIOUS_SUMMARY_USER_KEY,
            ],
        )

    async def get_novel_polish_prompt_values(self, db: AsyncSession) -> dict[str, str]:
        return await system_prompt_service.get_effective_values(
            db,
            [
                NOVEL_POLISH_SYSTEM_KEY,
                NOVEL_POLISH_USER_TEMPLATE_KEY,
                NOVEL_POLISH_DEFAULT_SUGGESTIONS_KEY,
            ],
        )

    async def get_novel_write_temperature(self, db: AsyncSession) -> float:
        return await system_prompt_service.get_effective_float(
            db, NOVEL_WRITE_TEMPERATURE_KEY
        )

    async def get_novel_polish_temperature(self, db: AsyncSession) -> float:
        return await system_prompt_service.get_effective_float(
            db, NOVEL_POLISH_TEMPERATURE_KEY
        )

    async def get_list(
        self, db: AsyncSession, project_id: str
    ) -> list[Chapter]:
        result = await db.execute(
            select(Chapter)
            .where(Chapter.project_id == project_id)
            .order_by(Chapter.sort_order)
        )
        return list(result.scalars().all())

    async def get_by_id(self, db: AsyncSession, chapter_id: str) -> Chapter | None:
        return await db.get(Chapter, chapter_id)

    async def create(self, db: AsyncSession, project_id: str, data: ChapterCreate) -> Chapter:
        chapter = Chapter(
            project_id=project_id,
            outline_node_id=data.outline_node_id,
            title=data.title,
            content=data.content,
            sort_order=data.sort_order,
        )
        db.add(chapter)
        await db.commit()
        await db.refresh(chapter)
        return chapter

    async def update(
        self, db: AsyncSession, chapter_id: str, data: ChapterUpdate
    ) -> Chapter | None:
        chapter = await db.get(Chapter, chapter_id)
        if not chapter:
            return None
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(chapter, key, value)
        await db.commit()
        await db.refresh(chapter)
        return chapter

    async def delete(self, db: AsyncSession, chapter_id: str) -> bool:
        chapter = await db.get(Chapter, chapter_id)
        if not chapter:
            return False
        await db.delete(chapter)
        await db.commit()
        return True

    async def save_version(
        self, db: AsyncSession, chapter_id: str, data: VersionCreate
    ) -> ChapterVersion:
        chapter = await db.get(Chapter, chapter_id)
        if not chapter:
            return None
        latest = await self._get_latest_version(db, chapter_id)
        next_v = (latest.version_number + 1) if latest else 1
        version = ChapterVersion(
            chapter_id=chapter_id,
            version_number=next_v,
            content=chapter.content or "",
            word_count=chapter.word_count,
            change_summary=data.change_summary,
        )
        db.add(version)
        await db.commit()
        await db.refresh(version)
        return version

    async def get_versions(
        self, db: AsyncSession, chapter_id: str
    ) -> list[ChapterVersion]:
        result = await db.execute(
            select(ChapterVersion)
            .where(ChapterVersion.chapter_id == chapter_id)
            .order_by(ChapterVersion.version_number.desc())
        )
        return list(result.scalars().all())

    async def compare_versions(
        self, db: AsyncSession, chapter_id: str, v1: int, v2: int
    ) -> dict:
        ver1 = await self._get_version(db, chapter_id, v1)
        ver2 = await self._get_version(db, chapter_id, v2)
        if not ver1 or not ver2:
            return None
        lines1 = ver1.content.splitlines(keepends=True)
        lines2 = ver2.content.splitlines(keepends=True)
        diff = list(difflib.unified_diff(lines1, lines2, lineterm=""))
        additions = sum(
            1 for line in diff if line.startswith("+") and not line.startswith("+++")
        )
        deletions = sum(
            1 for line in diff if line.startswith("-") and not line.startswith("---")
        )
        html_diff = difflib.HtmlDiff().make_table(lines1, lines2)
        return {
            "version1": v1,
            "version2": v2,
            "additions": additions,
            "deletions": deletions,
            "unified_diff": diff,
            "html_diff": html_diff,
        }

    async def ai_assist(
        self,
        db: AsyncSession,
        llm_config_id: str,
        chapter_id: str,
        action: str,
        selection: str | None = None,
        context: str | None = None,
    ) -> dict:
        chapter = await db.get(Chapter, chapter_id)
        if not chapter:
            return None

        if action == "continue":
            temperature = await system_prompt_service.get_effective_float(
                db, CHAPTER_CONTINUE_TEMPERATURE_KEY
            )
            messages = [
                {"role": "system", "content": CHAPTER_CONTINUE_SYSTEM},
                {
                    "role": "user",
                    "content": CHAPTER_CONTINUE_USER.format(
                        previous_content=chapter.content or "",
                        requirements=context or "",
                    ),
                },
            ]
            result = await llm_orchestrator.chat(
                llm_config_id, messages, temperature=temperature
            )
        elif action in ("rewrite", "polish", "expand"):
            system_map = {
                "rewrite": CHAPTER_REWRITE_SYSTEM,
                "polish": CHAPTER_POLISH_SYSTEM,
                "expand": CHAPTER_EXPAND_SYSTEM,
            }
            user_map = {
                "rewrite": CHAPTER_REWRITE_USER,
                "polish": CHAPTER_POLISH_USER,
                "expand": CHAPTER_EXPAND_USER,
            }
            temperature_key_map = {
                "rewrite": CHAPTER_REWRITE_TEMPERATURE_KEY,
                "polish": CHAPTER_POLISH_TEMPERATURE_KEY,
                "expand": CHAPTER_EXPAND_TEMPERATURE_KEY,
            }
            system_prompt = system_map[action]
            user_template = user_map[action]
            temperature = await system_prompt_service.get_effective_float(
                db, temperature_key_map[action]
            )
            format_kwargs = {
                "selected_text": selection or "",
                "context": context or "",
                "action": action,
            }
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_template.format(**format_kwargs),
                },
            ]
            result = await llm_orchestrator.chat(
                llm_config_id, messages, temperature=temperature
            )
        elif action == "summarize":
            temperature = await system_prompt_service.get_effective_float(
                db, CHAPTER_SUMMARIZE_TEMPERATURE_KEY
            )
            messages = [
                {"role": "system", "content": CHAPTER_SUMMARIZE_SYSTEM},
                {
                    "role": "user",
                    "content": CHAPTER_SUMMARIZE_USER.format(
                        chapter_content=chapter.content or ""
                    ),
                },
            ]
            result = await llm_orchestrator.chat(
                llm_config_id, messages, temperature=temperature
            )
        elif action == "dialogue":
            temperature = await system_prompt_service.get_effective_float(
                db, CHAPTER_DIALOGUE_TEMPERATURE_KEY
            )
            messages = [
                {"role": "system", "content": CHAPTER_DIALOGUE_SYSTEM},
                {
                    "role": "user",
                    "content": CHAPTER_DIALOGUE_USER.format(
                        context=context or "",
                        scene_context=chapter.content or "",
                    ),
                },
            ]
            result = await llm_orchestrator.chat(
                llm_config_id, messages, temperature=temperature
            )
        else:
            return None

        return {
            "content": result,
            "action": action,
            "tokens_used": 0,
        }

    async def ai_stream(
        self,
        db: AsyncSession,
        llm_config_id: str,
        chapter_id: str,
        action: str,
        selection: str | None = None,
        context: str | None = None,
    ) -> AsyncIterator[str]:
        chapter = await db.get(Chapter, chapter_id)
        if not chapter:
            return

        if action == "continue":
            temperature_key = CHAPTER_CONTINUE_TEMPERATURE_KEY
            messages = [
                {"role": "system", "content": CHAPTER_CONTINUE_SYSTEM},
                {
                    "role": "user",
                    "content": CHAPTER_CONTINUE_USER.format(
                        previous_content=chapter.content or "",
                        requirements=context or "",
                    ),
                },
            ]
        else:
            temperature_key = {
                "rewrite": CHAPTER_REWRITE_TEMPERATURE_KEY,
                "polish": CHAPTER_POLISH_TEMPERATURE_KEY,
                "expand": CHAPTER_EXPAND_TEMPERATURE_KEY,
                "dialogue": CHAPTER_DIALOGUE_TEMPERATURE_KEY,
                "summarize": CHAPTER_SUMMARIZE_TEMPERATURE_KEY,
            }.get(action, CHAPTER_REWRITE_TEMPERATURE_KEY)
            messages = [
                {"role": "system", "content": CHAPTER_REWRITE_SYSTEM},
                {
                    "role": "user",
                    "content": CHAPTER_REWRITE_USER.format(
                        selected_text=selection or "",
                        context=context or "",
                        action=action,
                    ),
                },
            ]

        temperature = await system_prompt_service.get_effective_float(
            db, temperature_key
        )
        async for chunk in llm_orchestrator.stream_chat(
            llm_config_id, messages, temperature=temperature
        ):
            yield chunk

    async def build_novel_write_context(
        self,
        db: AsyncSession,
        project_id: str,
        chapter_id: str,
        style_requirements: str | None = None,
        overrides: NovelWriteContextOverride | None = None,
    ) -> dict | None:
        chapter = await db.get(Chapter, chapter_id)
        if not chapter:
            return None

        chapter_title = chapter.title
        current_outline_node = None
        volume_node = None
        outline_node_title = None
        chapter_summary = chapter.summary or ""
        outline_id = None
        outline_title = None
        outline_context = "暂无大纲信息"
        volume_node_id = None
        volume_title = None
        volume_context = "暂无卷信息"
        if chapter.outline_node_id:
            node = await db.get(OutlineNode, chapter.outline_node_id)
            if node:
                current_outline_node = node
                outline_node_title = node.title
                chapter_title = node.title or chapter_title
                if node.summary:
                    chapter_summary = node.summary
                outline_id = node.outline_id
                outline = await db.get(Outline, node.outline_id)
                if outline:
                    outline_title = outline.title
                    outline_parts = [f"大纲标题：{outline.title}"]
                    if outline.description:
                        outline_parts.append(f"大纲描述：{outline.description}")
                    outline_context = "\n".join(outline_parts)

                current_node = node
                seen_node_ids = set()
                while current_node and current_node.id not in seen_node_ids:
                    seen_node_ids.add(current_node.id)
                    if current_node.node_type == "VOLUME":
                        volume_node_id = current_node.id
                        volume_title = current_node.title
                        volume_node = current_node
                        volume_parts = [f"卷标题：{current_node.title}"]
                        if current_node.summary:
                            volume_parts.append(f"卷摘要：{current_node.summary}")
                        volume_context = "\n".join(volume_parts)
                        break
                    if not current_node.parent_id:
                        break
                    current_node = await db.get(OutlineNode, current_node.parent_id)

        char_result = await db.execute(
            select(Character)
            .where(Character.project_id == project_id)
            .order_by(Character.sort_order, Character.created_at, Character.id)
        )
        characters = list(char_result.scalars().all())
        char_defs = []
        character_items = []
        for c in characters:
            parts = [f"姓名：{c.name}"]
            if c.aliases:
                parts.append(f"别名：{'、'.join(c.aliases)}")
            if c.basic_info:
                for k, v in c.basic_info.items():
                    parts.append(f"{k}：{v}")
            if c.personality:
                for k, v in c.personality.items():
                    parts.append(f"{k}：{v}")
            if c.growth_arc:
                for k, v in c.growth_arc.items():
                    parts.append(f"{k}：{v}")
            if c.biography:
                parts.append(f"人物小传：{c.biography}")
            if c.notes:
                parts.append(f"备注：{c.notes}")
            definition = "\n".join(parts)
            char_defs.append(definition)
            character_items.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "aliases": c.aliases or [],
                    "definition": definition,
                    "selected": True,
                }
            )
        character_definitions = (
            "\n\n".join(char_defs) if char_defs else "暂无人物定义"
        )

        scene_result = await db.execute(
            select(Scene)
            .where(Scene.project_id == project_id)
            .order_by(Scene.sort_order, Scene.created_at, Scene.id)
        )
        scenes = list(scene_result.scalars().all())
        scene_items = []
        for scene in scenes:
            parts = [f"场景：{scene.name}"]
            if scene.location:
                parts.append(f"地点：{scene.location}")
            if scene.time:
                parts.append(f"时间：{scene.time}")
            if scene.atmosphere:
                parts.append(f"氛围：{scene.atmosphere}")
            if scene.description:
                parts.append(f"描述：{scene.description}")
            if scene.details:
                parts.append(f"细节：{scene.details}")
            if scene.notes:
                parts.append(f"备注：{scene.notes}")
            scene_items.append(
                {
                    "id": scene.id,
                    "name": scene.name,
                    "definition": "\n".join(parts),
                    "selected": False,
                }
            )

        previous_sources = await self._get_previous_chapter_sources(
            db, project_id, chapter, current_outline_node, volume_node
        )
        previous_context = self._build_previous_context_from_sources(
            previous_sources
        )
        previous_chapter_title = None
        previous_chapter_content = ""
        if previous_sources:
            previous_source = previous_sources[-1]
            previous_chapter_title = previous_source["title"]
            previous_chapter_content = self._clip_text(
                previous_source["content"], PREVIOUS_CHAPTER_CONTENT_LIMIT
            )

        default_style_requirements = await system_prompt_service.get_effective_value(
            db, NOVEL_WRITE_DEFAULT_STYLE_KEY
        )
        write_context = {
            "chapter_id": chapter.id,
            "outline_id": outline_id,
            "outline_title": outline_title,
            "outline_context": outline_context,
            "volume_node_id": volume_node_id,
            "volume_title": volume_title,
            "volume_context": volume_context,
            "chapter_title": chapter_title or "未命名章节",
            "outline_node_id": chapter.outline_node_id,
            "outline_node_title": outline_node_title,
            "chapter_summary": chapter_summary or "无章节摘要",
            "character_definitions": character_definitions,
            "characters": character_items,
            "character_count": len(characters),
            "scene_context": "暂无场景信息",
            "scenes": scene_items,
            "scene_count": len(scenes),
            "previous_chapter_title": previous_chapter_title,
            "previous_context": previous_context or "无前文背景",
            "previous_chapter_content": previous_chapter_content or "无前一章内容",
            "style_requirements": style_requirements or default_style_requirements,
        }
        return self.apply_novel_write_context_overrides(
            write_context, overrides
        )

    async def summarize_previous_context(
        self,
        db: AsyncSession,
        llm_config_id: str,
        project_id: str,
        chapter_id: str,
        style_requirements: str | None = None,
    ) -> dict | None:
        chapter = await db.get(Chapter, chapter_id)
        if not chapter:
            return None

        current_outline_node = None
        volume_node = None
        if chapter.outline_node_id:
            current_outline_node = await db.get(
                OutlineNode, chapter.outline_node_id
            )
            volume_node = await self._find_volume_node(db, current_outline_node)

        previous_sources = await self._get_previous_chapter_sources(
            db, project_id, chapter, current_outline_node, volume_node
        )
        if not previous_sources:
            return {"previous_context": "无前文背景", "chapter_count": 0}

        write_context = await self.build_novel_write_context(
            db, project_id, chapter_id, style_requirements
        )
        source_text = self._format_previous_chapters_for_ai_summary(
            previous_sources
        )
        prompt_values = await self.get_novel_previous_summary_prompt_values(db)
        messages = [
            {
                "role": "system",
                "content": prompt_values[NOVEL_WRITE_PREVIOUS_SUMMARY_SYSTEM_KEY],
            },
            {
                "role": "user",
                "content": prompt_values[NOVEL_WRITE_PREVIOUS_SUMMARY_USER_KEY].format(
                    volume_context=write_context["volume_context"],
                    chapter_title=write_context["chapter_title"],
                    chapter_summary=write_context["chapter_summary"],
                    previous_chapters=source_text,
                ),
            },
        ]
        temperature = await system_prompt_service.get_effective_float(
            db, NOVEL_WRITE_PREVIOUS_SUMMARY_TEMPERATURE_KEY
        )
        result = await llm_orchestrator.chat(
            llm_config_id, messages, temperature=temperature
        )
        previous_context = result.strip() or self._build_previous_context_from_sources(
            previous_sources
        )
        return {
            "previous_context": previous_context,
            "chapter_count": len(previous_sources),
        }

    async def _find_volume_node(
        self, db: AsyncSession, node: OutlineNode | None
    ) -> OutlineNode | None:
        current_node = node
        seen_node_ids = set()
        while current_node and current_node.id not in seen_node_ids:
            seen_node_ids.add(current_node.id)
            if current_node.node_type == "VOLUME":
                return current_node
            if not current_node.parent_id:
                return None
            current_node = await db.get(OutlineNode, current_node.parent_id)
        return None

    async def _get_previous_chapter_sources(
        self,
        db: AsyncSession,
        project_id: str,
        chapter: Chapter,
        current_outline_node: OutlineNode | None,
        volume_node: OutlineNode | None,
    ) -> list[dict[str, str]]:
        if current_outline_node and volume_node:
            node_result = await db.execute(
                select(OutlineNode)
                .where(
                    OutlineNode.outline_id == current_outline_node.outline_id,
                    OutlineNode.parent_id == volume_node.id,
                    OutlineNode.node_type == "CHAPTER",
                    OutlineNode.sort_order < current_outline_node.sort_order,
                )
                .order_by(OutlineNode.sort_order)
            )
            previous_nodes = list(node_result.scalars().all())
            if previous_nodes:
                node_ids = [node.id for node in previous_nodes]
                chapter_result = await db.execute(
                    select(Chapter).where(
                        Chapter.project_id == project_id,
                        Chapter.outline_node_id.in_(node_ids),
                    )
                )
                chapters_by_node_id = {
                    c.outline_node_id: c for c in chapter_result.scalars().all()
                }
                return [
                    self._build_previous_chapter_source(
                        chapters_by_node_id.get(node.id), node
                    )
                    for node in previous_nodes
                ]

        chapter_result = await db.execute(
            select(Chapter)
            .where(
                Chapter.project_id == project_id,
                Chapter.sort_order < chapter.sort_order,
            )
            .order_by(Chapter.sort_order)
        )
        return [
            self._build_previous_chapter_source(previous_chapter, None)
            for previous_chapter in chapter_result.scalars().all()
        ]

    def _build_previous_chapter_source(
        self,
        chapter: Chapter | None,
        node: OutlineNode | None,
    ) -> dict[str, str]:
        title = ""
        if node:
            title = node.title or ""
        if chapter and chapter.title and not title:
            title = chapter.title

        summary = ""
        if chapter and chapter.summary:
            summary = chapter.summary
        elif node and node.summary:
            summary = node.summary

        content = chapter.content if chapter and chapter.content else ""
        return {
            "title": title or "未命名章节",
            "summary": summary.strip(),
            "content": content.strip(),
        }

    def _build_previous_context_from_sources(
        self, sources: list[dict[str, str]]
    ) -> str:
        parts = []
        for index, source in enumerate(sources, start=1):
            summary = source["summary"]
            if not summary and source["content"]:
                summary = self._clip_text(
                    source["content"], PREVIOUS_CONTEXT_EXCERPT_LIMIT
                )
            if not summary:
                summary = "暂无摘要或正文"
            parts.append(f"{index}. {source['title']}\n摘要：{summary}")
        return "\n\n".join(parts)

    def _format_previous_chapters_for_ai_summary(
        self, sources: list[dict[str, str]]
    ) -> str:
        parts = []
        total_chars = 0
        for index, source in enumerate(sources, start=1):
            content = self._clip_text(
                source["content"], PREVIOUS_CONTEXT_SUMMARY_SOURCE_LIMIT
            )
            block_parts = [f"第{index}章：{source['title']}"]
            if source["summary"]:
                block_parts.append(f"已有摘要：{source['summary']}")
            if content:
                block_parts.append(f"章节正文摘录：\n{content}")
            else:
                block_parts.append("章节正文摘录：暂无正文")
            block = "\n".join(block_parts)
            if total_chars + len(block) > PREVIOUS_CONTEXT_SUMMARY_TOTAL_LIMIT:
                break
            parts.append(block)
            total_chars += len(block)
        return "\n\n".join(parts)

    @staticmethod
    def _clip_text(text: str, limit: int) -> str:
        cleaned = (text or "").strip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[-limit:]

    def apply_novel_write_context_overrides(
        self,
        write_context: dict,
        overrides: NovelWriteContextOverride | None = None,
    ) -> dict:
        if not overrides:
            return write_context

        override_data = overrides.model_dump(exclude_none=True)
        for key in (
            "outline_context",
            "volume_context",
            "chapter_title",
            "chapter_summary",
            "character_definitions",
            "scene_context",
            "previous_context",
            "previous_chapter_content",
            "style_requirements",
        ):
            if key in override_data:
                value = override_data[key]
                write_context[key] = value.strip() if isinstance(value, str) else value

        if not write_context.get("outline_context"):
            write_context["outline_context"] = "暂无大纲信息"
        if not write_context.get("volume_context"):
            write_context["volume_context"] = "暂无卷信息"
        if not write_context.get("chapter_title"):
            write_context["chapter_title"] = "未命名章节"
        if not write_context.get("chapter_summary"):
            write_context["chapter_summary"] = "无章节摘要"
        if not write_context.get("character_definitions"):
            write_context["character_definitions"] = "暂无人物定义"
        if not write_context.get("scene_context"):
            write_context["scene_context"] = "暂无场景信息"
        if not write_context.get("previous_context"):
            write_context["previous_context"] = "无前文背景"
        if not write_context.get("previous_chapter_content"):
            write_context["previous_chapter_content"] = "无前一章内容"
        if not write_context.get("style_requirements"):
            write_context["style_requirements"] = DEFAULT_NOVEL_STYLE_REQUIREMENTS
        return write_context

    def build_novel_write_messages(
        self,
        write_context: dict,
        prompt_values: dict[str, str] | None = None,
    ) -> list[dict[str, str]]:
        system_prompt = (
            prompt_values.get(NOVEL_WRITE_SYSTEM_KEY, NOVEL_WRITE_SYSTEM)
            if prompt_values
            else NOVEL_WRITE_SYSTEM
        )
        user_template = (
            prompt_values.get(NOVEL_WRITE_USER_TEMPLATE_KEY, NOVEL_WRITE_USER)
            if prompt_values
            else NOVEL_WRITE_USER
        )
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_template.format(
                    outline_context=write_context["outline_context"],
                    volume_context=write_context["volume_context"],
                    chapter_title=write_context["chapter_title"],
                    chapter_summary=write_context["chapter_summary"],
                    character_definitions=write_context["character_definitions"],
                    scene_context=write_context["scene_context"],
                    previous_context=write_context["previous_context"],
                    previous_chapter_content=write_context[
                        "previous_chapter_content"
                    ],
                    style_requirements=write_context["style_requirements"],
                ),
            },
        ]

    def build_novel_write_continuation_messages(
        self,
        write_context: dict,
        partial_content: str,
        prompt_values: dict[str, str] | None = None,
    ) -> list[dict[str, str]]:
        continuation_user = (
            prompt_values.get(
                NOVEL_WRITE_CONTINUATION_USER_KEY,
                NOVEL_WRITE_CONTINUATION_USER,
            )
            if prompt_values
            else NOVEL_WRITE_CONTINUATION_USER
        )
        messages = self.build_novel_write_messages(write_context, prompt_values)
        messages.append(
            {
                "role": "assistant",
                "content": self._clip_text(
                    partial_content, NOVEL_WRITE_CONTINUATION_CONTEXT_LIMIT
                ),
            }
        )
        messages.append({"role": "user", "content": continuation_user})
        return messages

    def build_novel_polish_messages(
        self,
        chapter_content: str,
        polish_suggestions: str,
        prompt_values: dict[str, str] | None = None,
    ) -> list[dict[str, str]]:
        system_prompt = (
            prompt_values.get(NOVEL_POLISH_SYSTEM_KEY, NOVEL_POLISH_SYSTEM)
            if prompt_values
            else NOVEL_POLISH_SYSTEM
        )
        user_template = (
            prompt_values.get(NOVEL_POLISH_USER_TEMPLATE_KEY, NOVEL_POLISH_USER)
            if prompt_values
            else NOVEL_POLISH_USER
        )
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_template.format(
                    chapter_content=chapter_content,
                    polish_suggestions=polish_suggestions,
                ),
            },
        ]

    async def novel_polish(
        self,
        db: AsyncSession,
        llm_config_id: str,
        project_id: str,
        chapter_id: str,
        polish_suggestions: str,
        chapter_content: str | None = None,
    ) -> dict | None:
        chapter = await db.get(Chapter, chapter_id)
        if not chapter or chapter.project_id != project_id:
            return None

        source_content = (
            chapter_content if chapter_content is not None else chapter.content or ""
        ).strip()
        prompt_values = await self.get_novel_polish_prompt_values(db)
        default_suggestions = prompt_values[NOVEL_POLISH_DEFAULT_SUGGESTIONS_KEY]
        messages = self.build_novel_polish_messages(
            source_content,
            polish_suggestions.strip() or default_suggestions,
            prompt_values,
        )
        result = await llm_orchestrator.chat(
            llm_config_id,
            messages,
            temperature=await system_prompt_service.get_effective_float(
                db, NOVEL_POLISH_TEMPERATURE_KEY
            ),
            max_tokens=NOVEL_WRITE_MAX_TOKENS,
        )

        chapter.content = result
        cn_chars = len(re.findall(r"[\u4e00-\u9fff]", result))
        chapter.word_count = cn_chars
        await db.commit()
        await db.refresh(chapter)

        return {
            "content": result,
            "word_count": cn_chars,
            "chapter_id": chapter_id,
        }

    async def novel_write(
        self,
        db: AsyncSession,
        llm_config_id: str,
        project_id: str,
        chapter_id: str,
        style_requirements: str | None = None,
        overrides: NovelWriteContextOverride | None = None,
    ) -> dict:
        chapter = await db.get(Chapter, chapter_id)
        if not chapter:
            return None

        write_context = await self.build_novel_write_context(
            db, project_id, chapter_id, style_requirements, overrides
        )
        prompt_values = await self.get_novel_write_prompt_values(db)
        messages = self.build_novel_write_messages(write_context, prompt_values)
        result = await llm_orchestrator.chat(
            llm_config_id,
            messages,
            temperature=await self.get_novel_write_temperature(db),
            max_tokens=NOVEL_WRITE_MAX_TOKENS,
        )

        chapter.content = result
        cn_chars = len(re.findall(r'[\u4e00-\u9fff]', result))
        chapter.word_count = cn_chars
        await db.commit()
        await db.refresh(chapter)

        return {
            "content": result,
            "word_count": cn_chars,
            "chapter_id": chapter_id,
            "write_context": write_context,
        }

    async def _get_version(
        self, db: AsyncSession, chapter_id: str, num: int
    ) -> ChapterVersion | None:
        result = await db.execute(
            select(ChapterVersion).where(
                ChapterVersion.chapter_id == chapter_id,
                ChapterVersion.version_number == num,
            )
        )
        return result.scalar_one_or_none()

    async def _get_latest_version(
        self, db: AsyncSession, chapter_id: str
    ) -> ChapterVersion | None:
        result = await db.execute(
            select(ChapterVersion)
            .where(ChapterVersion.chapter_id == chapter_id)
            .order_by(ChapterVersion.version_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


chapter_service = ChapterService()
