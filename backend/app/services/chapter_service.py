import difflib
import json
import re
from typing import Any, AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter, ChapterVersion
from app.models.character import Character, CharacterRelationship
from app.models.outline import Outline, OutlineNode
from app.models.project import Project
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
from app.llm.prompts.long_novel import (
    LONG_NOVEL_POLISH_SYSTEM_PREFIX,
    LONG_NOVEL_SCHEMA_VERSION,
    LONG_NOVEL_WRITER_SYSTEM_PREFIX,
    ensure_stable_system_prefix,
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
NOVEL_WRITE_MAX_TOKENS = 8192 * 2
POLISH_ADJACENT_CHAPTER_CONTENT_LIMIT = 4000
NOVEL_WRITE_DEFAULT_TARGET_CHARS = 4000
NOVEL_WRITE_MIN_TARGET_CHARS = 1500
NOVEL_WRITE_MAX_TARGET_CHARS = 12000


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

    async def get_novel_previous_summary_prompt_values(self, db: AsyncSession) -> dict[str, str]:
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
        return await system_prompt_service.get_effective_float(db, NOVEL_WRITE_TEMPERATURE_KEY)

    async def get_novel_polish_temperature(self, db: AsyncSession) -> float:
        return await system_prompt_service.get_effective_float(db, NOVEL_POLISH_TEMPERATURE_KEY)

    async def get_list(self, db: AsyncSession, project_id: str) -> list[Chapter]:
        result = await db.execute(
            select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.sort_order)
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

    async def get_versions(self, db: AsyncSession, chapter_id: str) -> list[ChapterVersion]:
        result = await db.execute(
            select(ChapterVersion)
            .where(ChapterVersion.chapter_id == chapter_id)
            .order_by(ChapterVersion.version_number.desc())
        )
        return list(result.scalars().all())

    async def compare_versions(self, db: AsyncSession, chapter_id: str, v1: int, v2: int) -> dict:
        ver1 = await self._get_version(db, chapter_id, v1)
        ver2 = await self._get_version(db, chapter_id, v2)
        if not ver1 or not ver2:
            return None
        lines1 = ver1.content.splitlines(keepends=True)
        lines2 = ver2.content.splitlines(keepends=True)
        diff = list(difflib.unified_diff(lines1, lines2, lineterm=""))
        additions = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
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
            result = await llm_orchestrator.chat(llm_config_id, messages, temperature=temperature)
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
            result = await llm_orchestrator.chat(llm_config_id, messages, temperature=temperature)
        elif action == "summarize":
            temperature = await system_prompt_service.get_effective_float(
                db, CHAPTER_SUMMARIZE_TEMPERATURE_KEY
            )
            messages = [
                {"role": "system", "content": CHAPTER_SUMMARIZE_SYSTEM},
                {
                    "role": "user",
                    "content": CHAPTER_SUMMARIZE_USER.format(chapter_content=chapter.content or ""),
                },
            ]
            result = await llm_orchestrator.chat(llm_config_id, messages, temperature=temperature)
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
            result = await llm_orchestrator.chat(llm_config_id, messages, temperature=temperature)
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

        temperature = await system_prompt_service.get_effective_float(db, temperature_key)
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
        *,
        include_project_story_state: bool = True,
        allow_entity_fallback: bool = True,
        character_refs_override: Any = None,
        scene_refs_override: Any = None,
        include_character_relationships: bool = False,
    ) -> dict | None:
        chapter = await db.get(Chapter, chapter_id)
        if not chapter or chapter.project_id != project_id:
            return None

        project = await db.get(Project, project_id)
        project_settings = self._parse_project_settings(project.settings if project else None)

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

        chapter_metadata = self._chapter_metadata(current_outline_node)
        character_ref_source = chapter_metadata.get("characters")
        if character_refs_override is not None:
            character_ref_source = character_refs_override
        scene_ref_source = chapter_metadata.get("scene_focus")
        if scene_refs_override is not None:
            scene_ref_source = scene_refs_override
        character_refs = self._normalize_metadata_refs(character_ref_source)
        scene_refs = self._normalize_metadata_refs(scene_ref_source)

        char_result = await db.execute(
            select(Character)
            .where(Character.project_id == project_id)
            .order_by(Character.sort_order, Character.created_at, Character.id)
        )
        characters = list(char_result.scalars().all())
        selected_characters, character_match_fallback = self._select_characters(
            characters,
            character_refs,
            allow_fallback=allow_entity_fallback,
        )
        selected_character_ids = {character.id for character in selected_characters}
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
            selected = c.id in selected_character_ids
            if selected:
                char_defs.append(definition)
            character_items.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "aliases": c.aliases or [],
                    "definition": definition,
                    "selected": selected,
                }
            )
        character_definitions = "\n\n".join(char_defs) if char_defs else "暂无人物定义"
        if include_character_relationships and selected_character_ids:
            relationship_result = await db.execute(
                select(CharacterRelationship)
                .where(
                    CharacterRelationship.project_id == project_id,
                    CharacterRelationship.source_id.in_(selected_character_ids),
                    CharacterRelationship.target_id.in_(selected_character_ids),
                )
                .order_by(
                    CharacterRelationship.created_at,
                    CharacterRelationship.id,
                )
            )
            relationships = list(relationship_result.scalars().all())
            if relationships:
                character_names = {item.id: item.name for item in selected_characters}
                character_definitions = "\n\n".join(
                    [
                        character_definitions,
                        *[
                            self._format_character_relationship(item, character_names)
                            for item in relationships
                        ],
                    ]
                )

        scene_result = await db.execute(
            select(Scene)
            .where(Scene.project_id == project_id)
            .order_by(Scene.sort_order, Scene.created_at, Scene.id)
        )
        scenes = list(scene_result.scalars().all())
        selected_scenes, scene_match_fallback = self._select_scenes(
            scenes,
            scene_refs,
            allow_fallback=allow_entity_fallback,
        )
        selected_scene_ids = {scene.id for scene in selected_scenes}
        scene_items = []
        selected_scene_definitions = []
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
            definition = "\n".join(parts)
            selected = scene.id in selected_scene_ids
            if selected:
                selected_scene_definitions.append(definition)
            scene_items.append(
                {
                    "id": scene.id,
                    "name": scene.name,
                    "definition": definition,
                    "selected": selected,
                }
            )
        scene_context = (
            "\n\n".join(selected_scene_definitions)
            if selected_scene_definitions
            else "暂无场景信息"
        )

        previous_sources = await self._get_previous_chapter_sources(
            db, project_id, chapter, current_outline_node, volume_node
        )
        previous_context = self._build_previous_context_from_sources(previous_sources)
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
        project_style_guide = self._setting_text(project_settings.get("style_guide"))
        effective_style_requirements = (
            (style_requirements or "").strip()
            or project_style_guide
            or default_style_requirements
            or DEFAULT_NOVEL_STYLE_REQUIREMENTS
        )
        (
            target_chars,
            target_chars_source,
            project_total_chapters,
        ) = await self._resolve_target_chars(
            db,
            project_id,
            project,
            chapter_metadata.get("target_chars"),
            outline_id=outline_id,
        )
        novel_bible_data = self._build_novel_bible(
            project,
            project_settings,
            project_style_guide,
            include_story_state=include_project_story_state,
        )
        contract_character_refs = character_refs or [
            character.name for character in selected_characters
        ]
        chapter_contract_data = {
            **chapter_metadata,
            "schema_version": LONG_NOVEL_SCHEMA_VERSION,
            "chapter_id": chapter.id,
            "title": chapter_title or "未命名章节",
            "summary": chapter_summary or "无章节摘要",
            "pov": self._setting_text(chapter_metadata.get("pov")) or "未指定",
            "scene_focus": chapter_metadata.get("scene_focus") or [],
            "characters": contract_character_refs,
            "hook": self._setting_text(chapter_metadata.get("hook")) or "未指定",
            "target_chars": target_chars,
            "target_chars_source": target_chars_source,
        }
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
            "selected_character_count": len(selected_characters),
            "character_match_fallback": character_match_fallback,
            "scene_context": scene_context,
            "scenes": scene_items,
            "scene_count": len(scenes),
            "selected_scene_count": len(selected_scenes),
            "scene_match_fallback": scene_match_fallback,
            "previous_chapter_title": previous_chapter_title,
            "previous_context": previous_context or "无前文背景",
            "previous_chapter_content": previous_chapter_content or "无前一章内容",
            "style_requirements": effective_style_requirements,
            "novel_bible": self._stable_json(novel_bible_data),
            "novel_bible_data": novel_bible_data,
            "chapter_metadata": chapter_metadata,
            "pov": chapter_contract_data["pov"],
            "scene_focus": chapter_metadata.get("scene_focus") or [],
            "chapter_character_refs": character_refs,
            "hook": chapter_contract_data["hook"],
            "target_chars": target_chars,
            "target_chars_source": target_chars_source,
            "project_total_chapters": project_total_chapters,
            "chapter_contract": self._stable_json(chapter_contract_data),
            "chapter_contract_data": chapter_contract_data,
        }
        return self.apply_novel_write_context_overrides(write_context, overrides)

    @staticmethod
    def _parse_project_settings(raw_settings: Any) -> dict[str, Any]:
        if isinstance(raw_settings, dict):
            return dict(raw_settings)
        if not isinstance(raw_settings, str) or not raw_settings.strip():
            return {}
        try:
            parsed = json.loads(raw_settings)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"legacy_settings": raw_settings.strip()}
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except (TypeError, ValueError, json.JSONDecodeError):
                return {"legacy_settings": str(parsed).strip()}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _chapter_metadata(node: OutlineNode | None) -> dict[str, Any]:
        metadata = node.metadata_ if node and isinstance(node.metadata_, dict) else {}
        return dict(metadata)

    @classmethod
    def _normalize_metadata_refs(cls, value: Any) -> list[str]:
        refs: list[str] = []

        def collect(item: Any) -> None:
            if item is None:
                return
            if isinstance(item, str):
                refs.extend(
                    part.strip() for part in re.split(r"[,，、;；|/\n]+", item) if part.strip()
                )
                return
            if isinstance(item, dict):
                for key in ("id", "name", "label"):
                    if item.get(key) is not None:
                        collect(item[key])
                        return
                return
            if isinstance(item, (list, tuple, set)):
                for child in item:
                    collect(child)
                return
            text = str(item).strip()
            if text:
                refs.append(text)

        collect(value)
        unique_refs: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            normalized = ref.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_refs.append(ref)
        return unique_refs

    @staticmethod
    def _reference_matches(ref: str, candidates: list[Any]) -> bool:
        normalized_ref = str(ref).strip().casefold()
        if not normalized_ref:
            return False
        for candidate in candidates:
            if candidate is None:
                continue
            normalized_candidate = str(candidate).strip().casefold()
            if not normalized_candidate:
                continue
            if normalized_ref == normalized_candidate:
                return True
            if len(normalized_ref) >= 2 and (
                normalized_ref in normalized_candidate or normalized_candidate in normalized_ref
            ):
                return True
        return False

    @staticmethod
    def _format_character_relationship(
        relationship: CharacterRelationship,
        character_names: dict[str, str],
    ) -> str:
        source = character_names.get(relationship.source_id, relationship.source_id)
        target = character_names.get(relationship.target_id, relationship.target_id)
        parts = [
            f"人物关系：{source} → {target}",
            f"类型：{relationship.relationship_type or 'OTHER'}",
        ]
        if relationship.description:
            parts.append(f"说明：{relationship.description}")
        if relationship.start_chapter:
            parts.append(f"起始章节：{relationship.start_chapter}")
        if relationship.end_chapter:
            parts.append(f"结束章节：{relationship.end_chapter}")
        return "\n".join(parts)

    @classmethod
    def _select_characters(
        cls,
        characters: list[Character],
        refs: list[str],
        *,
        allow_fallback: bool = True,
    ) -> tuple[list[Character], bool]:
        if not refs:
            return (list(characters) if allow_fallback else []), False
        matches = [
            character
            for character in characters
            if any(
                cls._reference_matches(
                    ref,
                    [character.id, character.name, *(character.aliases or [])],
                )
                for ref in refs
            )
        ]
        if matches:
            return matches, False
        # Interactive/legacy callers can recover from stale refs with all public
        # entities. Agent writing disables that fallback to keep each window strict.
        return (list(characters) if allow_fallback else []), bool(characters)

    @classmethod
    def _select_scenes(
        cls,
        scenes: list[Scene],
        refs: list[str],
        *,
        allow_fallback: bool = True,
    ) -> tuple[list[Scene], bool]:
        if not refs:
            # Preserve the legacy opt-in behavior when no chapter scene is declared.
            return [], False
        matches = [
            scene
            for scene in scenes
            if any(
                cls._reference_matches(
                    ref,
                    [scene.id, scene.name, scene.location],
                )
                for ref in refs
            )
        ]
        if matches:
            return matches, False
        return (list(scenes) if allow_fallback else []), bool(scenes)

    @staticmethod
    def _coerce_positive_int(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            if isinstance(value, str):
                value = value.strip().replace(",", "")
                if not value:
                    return None
            number = int(float(value))
        except (TypeError, ValueError, OverflowError):
            return None
        return number if number > 0 else None

    @staticmethod
    def _clamp_target_chars(value: int) -> int:
        return max(
            NOVEL_WRITE_MIN_TARGET_CHARS,
            min(NOVEL_WRITE_MAX_TARGET_CHARS, value),
        )

    async def _resolve_target_chars(
        self,
        db: AsyncSession,
        project_id: str,
        project: Project | None,
        metadata_target: Any,
        *,
        outline_id: str | None = None,
    ) -> tuple[int, str, int]:
        outline_count_query = select(func.count(OutlineNode.id)).where(
            OutlineNode.node_type == "CHAPTER"
        )
        if outline_id:
            outline_count_query = outline_count_query.where(
                OutlineNode.outline_id == outline_id
            )
        else:
            outline_count_query = outline_count_query.join(
                Outline, OutlineNode.outline_id == Outline.id
            ).where(Outline.project_id == project_id)
        outline_count_result = await db.execute(outline_count_query)
        chapter_count_result = await db.execute(
            select(func.count(Chapter.id)).where(Chapter.project_id == project_id)
        )
        outline_chapter_count = int(outline_count_result.scalar_one() or 0)
        stored_chapter_count = int(chapter_count_result.scalar_one() or 0)
        project_total_chapters = max(outline_chapter_count, stored_chapter_count, 1)

        target_chars = self._coerce_positive_int(metadata_target)
        if target_chars is not None:
            return (
                self._clamp_target_chars(target_chars),
                "outline_metadata",
                project_total_chapters,
            )

        project_word_target = self._coerce_positive_int(
            project.word_count_target if project else None
        )
        if project_word_target is not None:
            derived_target = round(project_word_target / project_total_chapters)
            return (
                self._clamp_target_chars(derived_target),
                "project_word_count",
                project_total_chapters,
            )

        return (
            NOVEL_WRITE_DEFAULT_TARGET_CHARS,
            "default",
            project_total_chapters,
        )

    @staticmethod
    def _stable_json(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    @classmethod
    def _setting_text(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (dict, list, tuple)):
            return cls._stable_json(value)
        return str(value).strip()

    @classmethod
    def _build_novel_bible(
        cls,
        project: Project | None,
        settings: dict[str, Any],
        project_style_guide: str,
        *,
        include_story_state: bool = True,
    ) -> dict[str, Any]:
        bible = {
            "schema_version": LONG_NOVEL_SCHEMA_VERSION,
            "project": {
                "name": project.name if project else "未命名项目",
                "description": (project.description or "") if project else "",
                "genre": (project.genre or "") if project else "",
                "word_count_target": project.word_count_target if project else None,
            },
            "world_rules": settings.get("world_rules") or [],
            "long_term_hooks": settings.get("long_term_hooks") or [],
            "ending_direction": settings.get("ending_direction") or "",
            "style_guide": project_style_guide,
        }
        legacy_settings = cls._setting_text(settings.get("legacy_settings"))
        if legacy_settings:
            bible["legacy_settings"] = legacy_settings
        if include_story_state:
            bible["story_state"] = settings.get("story_state") or {}
        return bible

    async def summarize_previous_context(
        self,
        db: AsyncSession,
        llm_config_id: str,
        project_id: str,
        chapter_id: str,
        style_requirements: str | None = None,
    ) -> dict | None:
        chapter = await db.get(Chapter, chapter_id)
        if not chapter or chapter.project_id != project_id:
            return None

        current_outline_node = None
        volume_node = None
        if chapter.outline_node_id:
            current_outline_node = await db.get(OutlineNode, chapter.outline_node_id)
            volume_node = await self._find_volume_node(db, current_outline_node)

        previous_sources = await self._get_previous_chapter_sources(
            db, project_id, chapter, current_outline_node, volume_node
        )
        if not previous_sources:
            return {"previous_context": "无前文背景", "chapter_count": 0}

        write_context = await self.build_novel_write_context(
            db, project_id, chapter_id, style_requirements
        )
        source_text = self._format_previous_chapters_for_ai_summary(previous_sources)
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
        result = await llm_orchestrator.chat(llm_config_id, messages, temperature=temperature)
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
                chapters_by_node_id = {c.outline_node_id: c for c in chapter_result.scalars().all()}
                return [
                    self._build_previous_chapter_source(chapters_by_node_id.get(node.id), node)
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

    def _build_previous_context_from_sources(self, sources: list[dict[str, str]]) -> str:
        parts = []
        for index, source in enumerate(sources, start=1):
            summary = source["summary"]
            if not summary and source["content"]:
                summary = self._clip_text(source["content"], PREVIOUS_CONTEXT_EXCERPT_LIMIT)
            if not summary:
                summary = "暂无摘要或正文"
            parts.append(f"{index}. {source['title']}\n摘要：{summary}")
        return "\n\n".join(parts)

    def _format_previous_chapters_for_ai_summary(self, sources: list[dict[str, str]]) -> str:
        parts = []
        total_chars = 0
        for index, source in enumerate(sources, start=1):
            content = self._clip_text(source["content"], PREVIOUS_CONTEXT_SUMMARY_SOURCE_LIMIT)
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
        override_data = overrides.model_dump(exclude_none=True) if overrides else {}
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
        if not write_context.get("novel_bible"):
            write_context["novel_bible"] = self._stable_json(
                {
                    "schema_version": LONG_NOVEL_SCHEMA_VERSION,
                    "world_rules": [],
                    "long_term_hooks": [],
                    "ending_direction": "",
                    "style_guide": "",
                }
            )
        contract = self._chapter_contract_from_context(write_context)
        write_context["chapter_contract_data"] = contract
        write_context["chapter_contract"] = self._stable_json(contract)
        write_context["target_chars"] = contract["target_chars"]
        return write_context

    def _chapter_contract_from_context(self, write_context: dict) -> dict[str, Any]:
        existing = write_context.get("chapter_contract_data")
        contract = dict(existing) if isinstance(existing, dict) else {}
        target_chars = self._coerce_positive_int(write_context.get("target_chars"))
        if target_chars is None:
            target_chars = self._coerce_positive_int(contract.get("target_chars"))
        target_chars = self._clamp_target_chars(target_chars or NOVEL_WRITE_DEFAULT_TARGET_CHARS)
        characters = write_context.get("chapter_character_refs")
        if characters is None:
            characters = contract.get("characters", [])
        scene_focus = write_context.get("scene_focus")
        if scene_focus is None:
            scene_focus = contract.get("scene_focus", [])
        contract.update(
            {
                "schema_version": LONG_NOVEL_SCHEMA_VERSION,
                "chapter_id": write_context.get("chapter_id") or contract.get("chapter_id"),
                "title": write_context.get("chapter_title") or "未命名章节",
                "summary": write_context.get("chapter_summary") or "无章节摘要",
                "pov": write_context.get("pov") or contract.get("pov") or "未指定",
                "scene_focus": scene_focus,
                "characters": characters,
                "hook": write_context.get("hook") or contract.get("hook") or "未指定",
                "target_chars": target_chars,
                "target_chars_source": write_context.get("target_chars_source")
                or contract.get("target_chars_source")
                or "default",
            }
        )
        return contract

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
        system_prompt = ensure_stable_system_prefix(system_prompt, LONG_NOVEL_WRITER_SYSTEM_PREFIX)
        user_template = (
            prompt_values.get(NOVEL_WRITE_USER_TEMPLATE_KEY, NOVEL_WRITE_USER)
            if prompt_values
            else NOVEL_WRITE_USER
        )
        chapter_contract = write_context.get("chapter_contract")
        if not chapter_contract:
            chapter_contract = self._stable_json(self._chapter_contract_from_context(write_context))
        scene_focus = write_context.get("scene_focus", [])
        if not isinstance(scene_focus, str):
            scene_focus = self._stable_json(scene_focus)
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_template.format(
                    novel_bible=write_context.get("novel_bible", "暂无小说圣经"),
                    chapter_contract=chapter_contract,
                    outline_context=write_context.get("outline_context", "暂无大纲信息"),
                    volume_context=write_context.get("volume_context", "暂无卷信息"),
                    chapter_title=write_context.get("chapter_title", "未命名章节"),
                    chapter_summary=write_context.get("chapter_summary", "无章节摘要"),
                    character_definitions=write_context.get(
                        "character_definitions", "暂无人物定义"
                    ),
                    scene_context=write_context.get("scene_context", "暂无场景信息"),
                    previous_context=write_context.get("previous_context", "无前文背景"),
                    continuity_snapshot=write_context.get("previous_context", "无前文背景"),
                    previous_chapter_content=write_context.get(
                        "previous_chapter_content", "无前一章内容"
                    ),
                    style_requirements=write_context.get(
                        "style_requirements", DEFAULT_NOVEL_STYLE_REQUIREMENTS
                    ),
                    target_chars=write_context.get(
                        "target_chars", NOVEL_WRITE_DEFAULT_TARGET_CHARS
                    ),
                    pov=write_context.get("pov", "未指定"),
                    scene_focus=scene_focus,
                    hook=write_context.get("hook", "未指定"),
                    chapter_metadata=self._stable_json(write_context.get("chapter_metadata", {})),
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
                "content": self._clip_text(partial_content, NOVEL_WRITE_CONTINUATION_CONTEXT_LIMIT),
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
        system_prompt = ensure_stable_system_prefix(system_prompt, LONG_NOVEL_POLISH_SYSTEM_PREFIX)
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

    async def build_novel_polish_source_content(
        self,
        db: AsyncSession,
        project_id: str,
        chapter: Chapter,
        source_content: str,
        include_previous_chapter: bool = False,
        include_next_chapter: bool = False,
    ) -> str:
        source_content = source_content.strip()
        context_parts = []
        if include_previous_chapter:
            previous_chapter = await self._get_adjacent_chapter(db, project_id, chapter, "previous")
            if previous_chapter:
                context_parts.append(
                    self._format_polish_adjacent_chapter("前一章节", previous_chapter)
                )

        if include_next_chapter:
            next_chapter = await self._get_adjacent_chapter(db, project_id, chapter, "next")
            if next_chapter:
                context_parts.append(self._format_polish_adjacent_chapter("后一章节", next_chapter))

        target_block = f"【需要打磨的当前章节正文】\n{source_content}"
        if not context_parts:
            return target_block

        context_text = "\n\n".join(context_parts)
        return (
            "【打磨参考上下文】\n"
            "以下相邻章节仅用于帮助保持剧情衔接、人物动机和信息一致性。"
            "它们是只读证据：不要改写、续写、拼接或输出这些章节。\n\n"
            f"{context_text}\n\n"
            f"{target_block}"
        )

    async def _get_adjacent_chapter(
        self,
        db: AsyncSession,
        project_id: str,
        chapter: Chapter,
        direction: str,
    ) -> Chapter | None:
        if direction == "previous":
            result = await db.execute(
                select(Chapter)
                .where(
                    Chapter.project_id == project_id,
                    Chapter.sort_order < chapter.sort_order,
                )
                .order_by(Chapter.sort_order.desc(), Chapter.created_at.desc())
                .limit(1)
            )
        else:
            result = await db.execute(
                select(Chapter)
                .where(
                    Chapter.project_id == project_id,
                    Chapter.sort_order > chapter.sort_order,
                )
                .order_by(Chapter.sort_order.asc(), Chapter.created_at.asc())
                .limit(1)
            )
        return result.scalar_one_or_none()

    def _format_polish_adjacent_chapter(
        self,
        label: str,
        chapter: Chapter,
    ) -> str:
        parts = [
            f"【{label}】",
            f"标题：{chapter.title or '未命名章节'}",
            f"章节摘要：{(chapter.summary or '').strip() or '暂无摘要'}",
        ]
        content = self._clip_text(chapter.content or "", POLISH_ADJACENT_CHAPTER_CONTENT_LIMIT)
        parts.append(f"章节正文摘录：\n{content or '暂无正文'}")
        return "\n".join(parts)

    async def novel_polish(
        self,
        db: AsyncSession,
        llm_config_id: str,
        project_id: str,
        chapter_id: str,
        polish_suggestions: str,
        chapter_content: str | None = None,
        include_previous_chapter: bool = False,
        include_next_chapter: bool = False,
        max_tokens: int | None = None,
    ) -> dict | None:
        chapter = await db.get(Chapter, chapter_id)
        if not chapter or chapter.project_id != project_id:
            return None

        source_content = (
            chapter_content if chapter_content is not None else chapter.content or ""
        ).strip()
        source_content = await self.build_novel_polish_source_content(
            db,
            project_id,
            chapter,
            source_content,
            include_previous_chapter,
            include_next_chapter,
        )
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
            max_tokens=max_tokens or NOVEL_WRITE_MAX_TOKENS,
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
        max_tokens: int | None = None,
        *,
        include_project_story_state: bool = True,
        allow_entity_fallback: bool = True,
        character_refs_override: Any = None,
        scene_refs_override: Any = None,
        include_character_relationships: bool = False,
    ) -> dict:
        """Generate one chapter from a freshly assembled, request-local context."""

        chapter = await db.get(Chapter, chapter_id)
        if not chapter or chapter.project_id != project_id:
            return None

        write_context = await self.build_novel_write_context(
            db,
            project_id,
            chapter_id,
            style_requirements,
            overrides,
            include_project_story_state=include_project_story_state,
            allow_entity_fallback=allow_entity_fallback,
            character_refs_override=character_refs_override,
            scene_refs_override=scene_refs_override,
            include_character_relationships=include_character_relationships,
        )
        prompt_values = await self.get_novel_write_prompt_values(db)
        messages = self.build_novel_write_messages(write_context, prompt_values)
        result = await llm_orchestrator.chat(
            llm_config_id,
            messages,
            temperature=await self.get_novel_write_temperature(db),
            max_tokens=max_tokens or NOVEL_WRITE_MAX_TOKENS,
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

    async def _get_latest_version(self, db: AsyncSession, chapter_id: str) -> ChapterVersion | None:
        result = await db.execute(
            select(ChapterVersion)
            .where(ChapterVersion.chapter_id == chapter_id)
            .order_by(ChapterVersion.version_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


chapter_service = ChapterService()
