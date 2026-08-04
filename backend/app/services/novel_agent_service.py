import json
import re
from typing import Any, AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.json_mode import json_object_response_kwargs
from app.llm.output_limits import model_output_token_budget
from app.models.character import Character
from app.models.chapter import Chapter
from app.models.llm_config import LLMConfig
from app.models.outline import Outline, OutlineNode
from app.models.project import Project
from app.models.scene import Scene
from app.schemas.chapter import NovelWriteContextOverride
from app.schemas.novel_agent import NovelAgentWriteRequest
from app.services.chapter_service import NOVEL_WRITE_MAX_TOKENS, chapter_service
from app.services.llm_orchestrator import llm_orchestrator
from app.services.system_prompt_service import (
    NOVEL_AGENT_BLUEPRINT_SYSTEM_KEY,
    NOVEL_AGENT_BLUEPRINT_TEMPERATURE_KEY,
    NOVEL_AGENT_BLUEPRINT_USER_TEMPLATE_KEY,
    system_prompt_service,
)

NOVEL_AGENT_BLUEPRINT_MAX_TOKENS = 32768
NOVEL_AGENT_STEP_DEFINITIONS = (
    ("plan_blueprint", "蓝图生成"),
    ("create_project", "项目信息生成"),
    ("create_outline", "大纲生成"),
    ("create_characters", "人物生成"),
    ("create_scenes", "场景生成"),
    ("create_chapters", "章节生成"),
    ("write_chapters", "内容生成"),
)
NOVEL_AGENT_STEP_LABELS = dict(NOVEL_AGENT_STEP_DEFINITIONS)


class NovelAgentOutputError(ValueError):
    """Raised when the planning model returns unusable agent JSON."""


class NovelAgentService:
    async def plan_from_idea(
        self,
        db: AsyncSession,
        data: NovelAgentWriteRequest,
    ) -> dict[str, Any]:
        blueprint = self._unwrap_blueprint(
            await self._generate_blueprint(db, data)
        )
        try:
            self._ensure_blueprint_shape(blueprint)
            self._ensure_blueprint_scale(
                blueprint,
                data.volume_count,
                data.chapter_count,
            )
        except NovelAgentOutputError as initial_error:
            try:
                blueprint = self._unwrap_blueprint(
                    await self._repair_blueprint(
                        db,
                        data,
                        blueprint,
                        str(initial_error),
                    )
                )
                self._ensure_blueprint_shape(blueprint)
                self._ensure_blueprint_scale(
                    blueprint,
                    data.volume_count,
                    data.chapter_count,
                )
            except NovelAgentOutputError as repair_error:
                raise NovelAgentOutputError(
                    "Agent 生成蓝图自动补全后仍不完整：" + str(repair_error)
                ) from repair_error
        return blueprint

    async def plan_from_idea_stream(
        self,
        db: AsyncSession,
        project_id: str,
        data: NovelAgentWriteRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        project = await db.get(Project, project_id)
        if not project:
            yield {"type": "result", "result": None}
            return

        yield {
            "type": "steps",
            "steps": [
                self._step_progress(step, "pending", "等待执行")
                for step, _label in NOVEL_AGENT_STEP_DEFINITIONS
            ],
        }
        try:
            yield {
                "type": "step",
                "step": self._step_progress(
                    "plan_blueprint",
                    "running",
                    "正在使用 LLM 生成结构化小说蓝图",
                ),
            }
            blueprint = await self.plan_from_idea(db, data)
            completed_step = self._step_progress(
                "plan_blueprint",
                "completed",
                "计划已生成，等待用户确认",
            )
            yield {"type": "step", "step": completed_step}
            yield {"type": "plan", "plan": blueprint}
            yield {
                "type": "steps",
                "steps": [
                    completed_step,
                    *[
                        self._step_progress(step, "pending", "等待用户确认")
                        for step, _label in NOVEL_AGENT_STEP_DEFINITIONS[1:]
                    ],
                ],
            }
        except Exception:
            yield {
                "type": "step",
                "step": self._step_progress(
                    "plan_blueprint",
                    "failed",
                    "计划生成失败",
                ),
            }
            raise

    async def execute_blueprint_stream(
        self,
        db: AsyncSession,
        project_id: str,
        data: NovelAgentWriteRequest,
        blueprint: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        project = await db.get(Project, project_id)
        if not project:
            yield {"type": "result", "result": None}
            return
        self._ensure_blueprint_shape(blueprint)
        self._ensure_blueprint_scale(
            blueprint,
            data.volume_count,
            data.chapter_count,
        )

        plan_completed = self._step_progress(
            "plan_blueprint",
            "completed",
            "计划已由用户确认",
        )
        yield {
            "type": "steps",
            "steps": [
                plan_completed,
                *[
                    self._step_progress(step, "pending", "等待执行")
                    for step, _label in NOVEL_AGENT_STEP_DEFINITIONS[1:]
                ],
            ],
        }

        steps: list[dict[str, Any]] = [plan_completed]
        current_step: str | None = None
        try:

            current_step = "create_project"
            yield {
                "type": "step",
                "step": self._step_progress(
                    current_step,
                    "running",
                    "正在整理项目名称、简介、题材和写作设置",
                ),
            }
            if data.update_project:
                self._apply_project_blueprint(project, blueprint)
                project_message = "已写入项目元信息"
            else:
                project_message = "已按设置跳过项目信息更新"
            completed_step = self._step_progress(
                current_step,
                "completed",
                project_message,
            )
            steps.append(completed_step)
            yield {"type": "step", "step": completed_step}

            current_step = "create_outline"
            yield {
                "type": "step",
                "step": self._step_progress(
                    current_step,
                    "running",
                    "正在根据蓝图生成分卷分章大纲",
                ),
            }
            outline = await self._create_outline(db, project_id, blueprint)
            completed_step = self._step_progress(
                current_step,
                "completed",
                "已创建分卷分章大纲",
            )
            steps.append(completed_step)
            yield {"type": "step", "step": completed_step}

            current_step = "create_characters"
            yield {
                "type": "step",
                "step": self._step_progress(
                    current_step,
                    "running",
                    "正在根据蓝图生成人物档案",
                ),
            }
            characters = await self._create_characters(db, project_id, blueprint)
            completed_step = self._step_progress(
                current_step,
                "completed",
                f"已创建 {len(characters)} 个人物档案",
                current=len(characters),
                total=len(characters),
            )
            steps.append(completed_step)
            yield {"type": "step", "step": completed_step}

            current_step = "create_scenes"
            yield {
                "type": "step",
                "step": self._step_progress(
                    current_step,
                    "running",
                    "正在根据蓝图生成场景卡片",
                ),
            }
            scenes = await self._create_scenes(db, project_id, blueprint)
            completed_step = self._step_progress(
                current_step,
                "completed",
                f"已创建 {len(scenes)} 个场景卡片",
                current=len(scenes),
                total=len(scenes),
            )
            steps.append(completed_step)
            yield {"type": "step", "step": completed_step}

            current_step = "create_chapters"
            yield {
                "type": "step",
                "step": self._step_progress(
                    current_step,
                    "running",
                    "正在按大纲顺序创建章节草稿",
                ),
            }
            chapter_nodes = await self._chapter_nodes(db, outline.id)
            chapters = await self._create_chapters(
                db, project_id, chapter_nodes, data.chapter_count
            )
            await db.commit()
            await db.refresh(project)
            await db.refresh(outline)
            for character in characters:
                await db.refresh(character)
            for scene in scenes:
                await db.refresh(scene)
            for chapter in chapters:
                await db.refresh(chapter)
            completed_step = self._step_progress(
                current_step,
                "completed",
                f"已创建 {len(chapters)} 个章节草稿",
                current=len(chapters),
                total=len(chapters),
            )
            steps.append(completed_step)
            yield {"type": "step", "step": completed_step}

            current_step = "write_chapters"
            written_chapters = []
            target_write_count = min(data.write_chapter_count, len(chapters))
            if target_write_count:
                content_message = f"准备生成 {target_write_count} 个章节正文"
            else:
                content_message = "本次设置为只生成结构，跳过正文写作"
            yield {
                "type": "step",
                "step": self._step_progress(
                    current_step,
                    "running",
                    content_message,
                    current=0,
                    total=target_write_count,
                ),
            }
            style_guide = self._text_value(blueprint.get("style_guide")) or (
                data.style_requirements or ""
            )
            scene_context = self._build_scene_context(scenes)
            chapter_output_tokens = await self._output_token_budget(
                db,
                data.llm_config_id,
                NOVEL_WRITE_MAX_TOKENS,
            )
            for index, chapter in enumerate(chapters[:target_write_count], start=1):
                yield {
                    "type": "step",
                    "step": self._step_progress(
                        current_step,
                        "running",
                        f"正在生成第 {index}/{target_write_count} 章：{chapter.title}",
                        current=index - 1,
                        total=target_write_count,
                    ),
                }
                result = await chapter_service.novel_write(
                    db,
                    data.llm_config_id,
                    project_id,
                    chapter.id,
                    style_guide,
                    NovelWriteContextOverride(
                        scene_context=scene_context,
                        style_requirements=style_guide or None,
                    ),
                    max_tokens=chapter_output_tokens,
                )
                if result:
                    updated = await db.get(Chapter, chapter.id)
                    if updated:
                        written_chapters.append(updated)
                yield {
                    "type": "step",
                    "step": self._step_progress(
                        current_step,
                        "running",
                        f"已完成第 {index}/{target_write_count} 章：{chapter.title}",
                        current=index,
                        total=target_write_count,
                    ),
                }
            completed_step = self._step_progress(
                current_step,
                "completed",
                f"已自动写作 {len(written_chapters)} 个章节正文",
                current=target_write_count,
                total=target_write_count,
            )
            steps.append(completed_step)
            yield {"type": "step", "step": completed_step}

            refreshed_chapters = await self._list_project_chapters(db, project_id)
            yield {
                "type": "result",
                "result": {
                    "project": project,
                    "outline": outline,
                    "characters": characters,
                    "scenes": scenes,
                    "chapters": refreshed_chapters,
                    "written_chapters": written_chapters,
                    "blueprint": blueprint,
                    "steps": steps,
                },
            }
        except Exception:
            if current_step:
                yield {
                    "type": "step",
                    "step": self._step_progress(
                        current_step,
                        "failed",
                        "执行失败",
                    ),
                }
            raise

    @staticmethod
    def _step_progress(
        step: str,
        status: str,
        message: str,
        current: int | None = None,
        total: int | None = None,
    ) -> dict[str, Any]:
        return {
            "step": step,
            "label": NOVEL_AGENT_STEP_LABELS[step],
            "status": status,
            "message": message,
            "current": current,
            "total": total,
        }

    async def _generate_blueprint(
        self,
        db: AsyncSession,
        data: NovelAgentWriteRequest,
    ) -> dict[str, Any]:
        messages, kwargs = await self._blueprint_request_context(db, data)
        return await self._request_blueprint(data.llm_config_id, messages, kwargs)

    async def _repair_blueprint(
        self,
        db: AsyncSession,
        data: NovelAgentWriteRequest,
        blueprint: dict[str, Any],
        validation_error: str,
    ) -> dict[str, Any]:
        messages, kwargs = await self._blueprint_request_context(db, data)
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": json.dumps(blueprint, ensure_ascii=False),
                },
                {
                    "role": "user",
                    "content": (
                        f"上一次返回的蓝图未通过结构校验：{validation_error}\n"
                        "请重新返回完整的蓝图 JSON 对象，不要只返回缺失片段。"
                        "顶层 project 和 outline 都必须是对象；outline 必须包含 "
                        "title、description 和 children，children 按要求包含分卷分章。"
                        "同时保留并补齐 characters、scenes、style_guide 和 agent_plan。"
                        "只返回合法 JSON 对象。"
                    ),
                },
            ]
        )
        return await self._request_blueprint(data.llm_config_id, messages, kwargs)

    async def _blueprint_request_context(
        self,
        db: AsyncSession,
        data: NovelAgentWriteRequest,
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        prompt_values = await system_prompt_service.get_effective_values(
            db,
            [
                NOVEL_AGENT_BLUEPRINT_SYSTEM_KEY,
                NOVEL_AGENT_BLUEPRINT_USER_TEMPLATE_KEY,
                NOVEL_AGENT_BLUEPRINT_TEMPERATURE_KEY,
            ],
        )
        user_prompt = prompt_values[NOVEL_AGENT_BLUEPRINT_USER_TEMPLATE_KEY].format(
            idea=data.idea.strip(),
            volume_count=data.volume_count,
            chapter_count=data.chapter_count,
            word_count_target=data.word_count_target,
            genre=data.genre or "由 Agent 根据作者想法判断",
            style_requirements=data.style_requirements or "由 Agent 自适应题材",
            extra_requirements=data.extra_requirements or "无",
        )
        scale_constraint = (
            "【规模硬性约束】\n"
            f"- outline 中必须恰好生成 {data.volume_count} 个 VOLUME 节点。\n"
            f"- 全书所有卷合计必须恰好生成 {data.chapter_count} 个 CHAPTER 节点；"
            "这是全书总章数，不是每卷章数。\n"
            "- 各卷章节数可以不同，请按剧情容量分配，不要求平均分配。\n"
            "- 返回前请统计所有卷的 CHAPTER 节点总数并确认符合上述数量。"
        )
        messages = [
            {
                "role": "system",
                "content": prompt_values[NOVEL_AGENT_BLUEPRINT_SYSTEM_KEY],
            },
            {
                "role": "user",
                "content": f"{user_prompt}\n\n{scale_constraint}",
            },
        ]
        kwargs = {
            "temperature": float(prompt_values[NOVEL_AGENT_BLUEPRINT_TEMPERATURE_KEY]),
            "max_tokens": await self._output_token_budget(
                db,
                data.llm_config_id,
                NOVEL_AGENT_BLUEPRINT_MAX_TOKENS,
            ),
            **json_object_response_kwargs(),
        }
        if await self._can_use_deepseek_responses_api(db, data):
            kwargs["api_mode"] = "responses"
        return messages, kwargs

    async def _request_blueprint(
        self,
        llm_config_id: str,
        messages: list[dict[str, str]],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        response = await llm_orchestrator.chat(llm_config_id, messages, **kwargs)
        blueprint = self._extract_json(response)
        if not isinstance(blueprint, dict):
            raise NovelAgentOutputError("Agent 生成蓝图必须是 JSON 对象")
        return blueprint

    async def _can_use_deepseek_responses_api(
        self,
        db: AsyncSession,
        data: NovelAgentWriteRequest,
    ) -> bool:
        if not data.use_deepseek_responses_api:
            return False
        config = await db.get(LLMConfig, data.llm_config_id)
        if not config or config.provider != "deepseek":
            return False
        return (config.model_name or "").strip() == "deepseek-v4-flash"

    @staticmethod
    async def _output_token_budget(
        db: AsyncSession,
        llm_config_id: str,
        default_tokens: int,
    ) -> int:
        config = await db.get(LLMConfig, llm_config_id)
        return model_output_token_budget(config, default_tokens)

    @staticmethod
    def _extract_json(text: str) -> Any:
        text = (text or "").strip()
        if not text:
            raise NovelAgentOutputError("Agent 生成未返回蓝图内容")
        if text.startswith("```"):
            first_newline = text.index("\n") if "\n" in text else len(text)
            text = text[first_newline + 1 :]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            if start == -1:
                raise NovelAgentOutputError("Agent 生成没有返回合法 JSON 对象")
            depth = 0
            for index in range(start, len(text)):
                if text[index] == "{":
                    depth += 1
                elif text[index] == "}":
                    depth -= 1
                    if depth == 0:
                        return json.loads(text[start : index + 1])
            return json.loads(text[start:])

    @staticmethod
    def _ensure_blueprint_shape(blueprint: dict[str, Any]) -> None:
        required = ("project", "outline")
        missing = [key for key in required if not isinstance(blueprint.get(key), dict)]
        if missing:
            raise NovelAgentOutputError(
                "Agent 生成蓝图缺少必要字段：" + "、".join(missing)
            )

    @classmethod
    def _ensure_blueprint_scale(
        cls,
        blueprint: dict[str, Any],
        expected_volume_count: int,
        expected_chapter_count: int,
    ) -> None:
        outline = blueprint.get("outline")
        children = outline.get("children") if isinstance(outline, dict) else None
        actual_volume_count, actual_chapter_count = cls._count_outline_nodes(children)
        if (
            actual_volume_count != expected_volume_count
            or actual_chapter_count != expected_chapter_count
        ):
            raise NovelAgentOutputError(
                "Agent 生成蓝图规模不符合要求："
                f"目标为 {expected_volume_count} 卷、全书共 {expected_chapter_count} 章，"
                f"实际为 {actual_volume_count} 卷、全书共 {actual_chapter_count} 章。"
                "章节数表示全书所有卷合计，不是每卷章节数"
            )

    @classmethod
    def _count_outline_nodes(cls, nodes: Any) -> tuple[int, int]:
        if not isinstance(nodes, list):
            return 0, 0
        volume_count = 0
        chapter_count = 0
        for item in nodes:
            if not isinstance(item, dict):
                continue
            node_type = item.get("node_type")
            if node_type == "VOLUME":
                volume_count += 1
            elif node_type == "CHAPTER":
                chapter_count += 1
            child_volumes, child_chapters = cls._count_outline_nodes(
                item.get("children")
            )
            volume_count += child_volumes
            chapter_count += child_chapters
        return volume_count, chapter_count

    @staticmethod
    def _unwrap_blueprint(blueprint: dict[str, Any]) -> dict[str, Any]:
        if isinstance(blueprint.get("project"), dict) and isinstance(
            blueprint.get("outline"), dict
        ):
            return blueprint
        for key in ("blueprint", "plan", "data", "result"):
            nested = blueprint.get(key)
            if not isinstance(nested, dict):
                continue
            if not isinstance(nested.get("project"), dict) and not isinstance(
                nested.get("outline"), dict
            ):
                continue
            merged = {**blueprint, **nested}
            merged.pop(key, None)
            return merged
        return blueprint

    def _apply_project_blueprint(self, project: Project, blueprint: dict[str, Any]) -> None:
        project_data = blueprint.get("project") or {}
        name = self._text_value(project_data.get("name"))
        description = self._text_value(project_data.get("description"))
        genre = self._text_value(project_data.get("genre"))
        word_count_target = self._int_value(project_data.get("word_count_target"))
        if name:
            project.name = name[:200]
        if description:
            project.description = description
        if genre:
            project.genre = genre[:100]
        if word_count_target:
            project.word_count_target = word_count_target
        settings = project_data.get("settings")
        if isinstance(settings, dict):
            settings = {
                **settings,
                "style_guide": self._text_value(blueprint.get("style_guide")) or "",
                "agent_plan": blueprint.get("agent_plan") or [],
            }
            project.settings = json.dumps(settings, ensure_ascii=False)

    async def _create_outline(
        self,
        db: AsyncSession,
        project_id: str,
        blueprint: dict[str, Any],
    ) -> Outline:
        outline_data = blueprint.get("outline") or {}
        outline = Outline(
            project_id=project_id,
            title=(self._text_value(outline_data.get("title")) or "Agent 长篇大纲")[
                :300
            ],
            description=self._text_value(outline_data.get("description")),
        )
        db.add(outline)
        await db.flush()
        children = outline_data.get("children")
        if not isinstance(children, list):
            children = []
        await self._save_outline_nodes(db, outline.id, None, children, 0)
        return outline

    async def _save_outline_nodes(
        self,
        db: AsyncSession,
        outline_id: str,
        parent_id: str | None,
        nodes_data: list[dict[str, Any]],
        start_order: int,
    ) -> None:
        for index, item in enumerate(nodes_data):
            if not isinstance(item, dict):
                continue
            node_type = item.get("node_type")
            if node_type not in {"VOLUME", "CHAPTER", "SCENE", "PLOT_POINT", "KEY_EVENT"}:
                node_type = "CHAPTER"
            node = OutlineNode(
                outline_id=outline_id,
                parent_id=parent_id,
                node_type=node_type,
                title=(self._text_value(item.get("title")) or "未命名节点")[:300],
                summary=self._text_value(item.get("summary")),
                sort_order=start_order + index,
                metadata_=item.get("metadata") if isinstance(item.get("metadata"), dict) else None,
                llm_generated=True,
            )
            db.add(node)
            await db.flush()
            children = item.get("children")
            if isinstance(children, list) and children:
                await self._save_outline_nodes(db, outline_id, node.id, children, 0)

    async def _create_characters(
        self,
        db: AsyncSession,
        project_id: str,
        blueprint: dict[str, Any],
    ) -> list[Character]:
        source = blueprint.get("characters")
        if not isinstance(source, list):
            source = []
        next_order = await self._next_sort_order(db, Character, project_id)
        created: list[Character] = []
        for index, item in enumerate(source):
            if not isinstance(item, dict):
                continue
            character = Character(
                project_id=project_id,
                name=(self._text_value(item.get("name")) or "未命名人物")[:100],
                aliases=self._list_of_strings(item.get("aliases")),
                basic_info=item.get("basic_info") if isinstance(item.get("basic_info"), dict) else None,
                personality=item.get("personality") if isinstance(item.get("personality"), dict) else None,
                growth_arc=item.get("growth_arc") if isinstance(item.get("growth_arc"), dict) else None,
                biography=self._text_value(item.get("biography")),
                setting_collection=self._text_value(item.get("setting_collection")),
                notes=self._text_value(item.get("notes")),
                sort_order=next_order + index,
            )
            db.add(character)
            created.append(character)
        return created

    async def _create_scenes(
        self,
        db: AsyncSession,
        project_id: str,
        blueprint: dict[str, Any],
    ) -> list[Scene]:
        source = blueprint.get("scenes")
        if not isinstance(source, list):
            source = []
        next_order = await self._next_sort_order(db, Scene, project_id)
        created: list[Scene] = []
        for index, item in enumerate(source):
            if not isinstance(item, dict):
                continue
            scene = Scene(
                project_id=project_id,
                name=(self._text_value(item.get("name")) or "未命名场景")[:100],
                location=self._text_value(item.get("location")),
                time=self._text_value(item.get("time")),
                atmosphere=self._text_value(item.get("atmosphere")),
                description=self._text_value(item.get("description")),
                details=self._text_value(item.get("details")),
                notes=self._text_value(item.get("notes")),
                sort_order=next_order + index,
            )
            db.add(scene)
            created.append(scene)
        return created

    async def _chapter_nodes(
        self,
        db: AsyncSession,
        outline_id: str,
    ) -> list[OutlineNode]:
        result = await db.execute(
            select(OutlineNode)
            .where(OutlineNode.outline_id == outline_id)
            .order_by(OutlineNode.sort_order, OutlineNode.created_at, OutlineNode.id)
        )
        nodes = list(result.scalars().all())
        by_parent: dict[str | None, list[OutlineNode]] = {}
        for node in nodes:
            by_parent.setdefault(node.parent_id, []).append(node)
        for siblings in by_parent.values():
            siblings.sort(key=lambda item: (item.sort_order, item.created_at, item.id))

        ordered: list[OutlineNode] = []

        def visit(parent_id: str | None) -> None:
            for node in by_parent.get(parent_id, []):
                if node.node_type == "CHAPTER":
                    ordered.append(node)
                visit(node.id)

        visit(None)
        return ordered

    async def _create_chapters(
        self,
        db: AsyncSession,
        project_id: str,
        chapter_nodes: list[OutlineNode],
        chapter_count: int,
    ) -> list[Chapter]:
        next_order = await self._next_sort_order(db, Chapter, project_id)
        created: list[Chapter] = []
        for index, node in enumerate(chapter_nodes[:chapter_count]):
            chapter = Chapter(
                project_id=project_id,
                outline_node_id=node.id,
                title=node.title or f"第{index + 1}章",
                summary=node.summary,
                content="",
                sort_order=next_order + index,
                status="draft",
                word_count=0,
            )
            db.add(chapter)
            created.append(chapter)
        return created

    async def _list_project_chapters(
        self,
        db: AsyncSession,
        project_id: str,
    ) -> list[Chapter]:
        result = await db.execute(
            select(Chapter)
            .where(Chapter.project_id == project_id)
            .order_by(Chapter.sort_order, Chapter.created_at, Chapter.id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def _next_sort_order(
        db: AsyncSession,
        model,
        project_id: str,
    ) -> int:
        result = await db.execute(
            select(func.max(model.sort_order)).where(model.project_id == project_id)
        )
        max_order = result.scalar()
        return (max_order if max_order is not None else -1) + 1

    @staticmethod
    def _build_scene_context(scenes: list[Scene]) -> str:
        if not scenes:
            return "暂无场景信息"
        blocks = []
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
            blocks.append("\n".join(parts))
        return "\n\n".join(blocks)

    @staticmethod
    def _text_value(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value).strip() or None

    @staticmethod
    def _int_value(value: Any) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            match = re.search(r"\d+", value)
            if match:
                return int(match.group())
        return None

    @staticmethod
    def _list_of_strings(value: Any) -> list[str] | None:
        if isinstance(value, list):
            items = [str(item).strip() for item in value if str(item).strip()]
            return items or None
        if isinstance(value, str):
            items = [
                item.strip()
                for item in value.replace("，", ",").replace("、", ",").split(",")
                if item.strip()
            ]
            return items or None
        return None


novel_agent_service = NovelAgentService()
