import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.json_mode import json_object_response_kwargs
from app.models.outline import Outline, OutlineNode
from app.schemas.outline import OutlineCreate, OutlineUpdate, OutlineNodeCreate, OutlineNodeUpdate
from app.services.llm_orchestrator import llm_orchestrator
from app.services.system_prompt_service import (
    OUTLINE_EXPAND_TEMPERATURE_KEY,
    OUTLINE_EXPAND_DEFAULT_COUNT_KEY,
    OUTLINE_EXPAND_SYSTEM_KEY,
    OUTLINE_GENERATE_TEMPERATURE_KEY,
    OUTLINE_OPTIMIZE_DEFAULT_DIRECTION_KEY,
    OUTLINE_OPTIMIZE_SYSTEM_KEY,
    OUTLINE_OPTIMIZE_TEMPERATURE_KEY,
    system_prompt_service,
)
from app.llm.prompts.outline import (
    OUTLINE_GENERATE_SYSTEM,
    OUTLINE_GENERATE_USER,
    OUTLINE_EXPAND_USER,
    OUTLINE_STRUCTURE_SYSTEM,
    OUTLINE_STRUCTURE_USER,
)


ALLOWED_NODE_TYPES = {"VOLUME", "CHAPTER", "SCENE", "PLOT_POINT", "KEY_EVENT"}


class OutlineService:
    async def get_list(self, db: AsyncSession, project_id: str) -> list[Outline]:
        result = await db.execute(
            select(Outline).where(Outline.project_id == project_id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, db: AsyncSession, outline_id: str) -> Outline | None:
        return await db.get(Outline, outline_id)

    async def create(self, db: AsyncSession, project_id: str, data: OutlineCreate) -> Outline:
        outline = Outline(
            project_id=project_id,
            title=data.title,
            description=data.description,
        )
        db.add(outline)
        await db.commit()
        await db.refresh(outline)
        return outline

    async def update(self, db: AsyncSession, outline_id: str, data: OutlineUpdate) -> Outline | None:
        outline = await db.get(Outline, outline_id)
        if not outline:
            return None
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(outline, key, value)
        await db.commit()
        await db.refresh(outline)
        return outline

    async def get_tree(self, db: AsyncSession, outline_id: str) -> dict | None:
        outline = await db.get(Outline, outline_id)
        if not outline:
            return None
        nodes = (
            await db.execute(
                select(OutlineNode).where(OutlineNode.outline_id == outline_id)
            )
        ).scalars().all()
        node_map = {n.id: n for n in nodes}
        root_nodes = sorted(
            [n for n in nodes if n.parent_id is None], key=lambda x: x.sort_order
        )
        tree = [self._build_tree(n, node_map) for n in root_nodes]
        return {"outline": outline, "tree": tree}

    def _build_tree(self, node: OutlineNode, node_map: dict) -> dict:
        children = sorted(
            [n for n in node_map.values() if n.parent_id == node.id],
            key=lambda x: x.sort_order,
        )
        return {
            "id": node.id,
            "node_type": node.node_type,
            "title": node.title,
            "summary": node.summary,
            "sort_order": node.sort_order,
            "metadata": node.metadata_,
            "llm_generated": node.llm_generated,
            "children": [self._build_tree(c, node_map) for c in children],
        }

    async def _get_siblings(
        self,
        db: AsyncSession,
        outline_id: str,
        parent_id: str | None,
    ) -> list[OutlineNode]:
        conditions = [OutlineNode.outline_id == outline_id]
        if parent_id is None:
            conditions.append(OutlineNode.parent_id.is_(None))
        else:
            conditions.append(OutlineNode.parent_id == parent_id)
        result = await db.execute(
            select(OutlineNode)
            .where(*conditions)
            .order_by(OutlineNode.sort_order, OutlineNode.created_at)
        )
        return list(result.scalars().all())

    async def _get_next_sort_order(
        self,
        db: AsyncSession,
        outline_id: str,
        parent_id: str | None,
    ) -> int:
        siblings = await self._get_siblings(db, outline_id, parent_id)
        if not siblings:
            return 0
        return max(node.sort_order for node in siblings) + 1

    async def _normalize_sibling_order(
        self,
        db: AsyncSession,
        outline_id: str,
        parent_id: str | None,
        moved_node: OutlineNode | None = None,
        new_order: int | None = None,
    ) -> None:
        siblings = await self._get_siblings(db, outline_id, parent_id)
        if moved_node:
            ordered = [node for node in siblings if node.id != moved_node.id]
            insert_at = max(0, min(new_order or 0, len(ordered)))
            ordered.insert(insert_at, moved_node)
        else:
            ordered = siblings
        for idx, node in enumerate(ordered):
            node.sort_order = idx

    async def generate_outline(
        self, db: AsyncSession, llm_config_id: str, project_id: str, params: dict
    ) -> Outline:
        messages = [
            {"role": "system", "content": OUTLINE_GENERATE_SYSTEM},
            {
                "role": "user",
                "content": OUTLINE_GENERATE_USER.format(
                    genre=params.get("genre", ""),
                    theme=params.get("theme", ""),
                    style=params.get("style", ""),
                    word_count_target=params.get("word_count_target", ""),
                    extra_requirements=params.get("extra_requirements", ""),
                ),
            },
        ]
        temperature = await system_prompt_service.get_effective_float(
            db, OUTLINE_GENERATE_TEMPERATURE_KEY
        )
        response = await llm_orchestrator.chat(
            llm_config_id,
            messages,
            temperature=temperature,
            **json_object_response_kwargs(),
        )
        outline_data = json.loads(response)
        outline = Outline(
            project_id=project_id,
            title=outline_data.get("title", "未命名大纲"),
            description=outline_data.get("description", ""),
        )
        db.add(outline)
        await db.flush()
        await self._save_nodes_recursive(
            db, outline.id, None, outline_data.get("children", []), 0
        )
        await db.commit()
        await db.refresh(outline)
        return outline

    async def _save_nodes_recursive(
        self,
        db: AsyncSession,
        outline_id: str,
        parent_id: str | None,
        nodes_data: list[dict],
        start_order: int,
    ) -> list[OutlineNode]:
        created = []
        for idx, nd in enumerate(nodes_data):
            node = OutlineNode(
                outline_id=outline_id,
                parent_id=parent_id,
                node_type=self._safe_node_type(nd.get("node_type"), "CHAPTER"),
                title=nd.get("title", ""),
                summary=nd.get("summary", ""),
                sort_order=start_order + idx,
                metadata_=nd.get("metadata"),
                llm_generated=True,
            )
            db.add(node)
            await db.flush()
            created.append(node)
            if children := nd.get("children"):
                await self._save_nodes_recursive(
                    db, outline_id, node.id, children, 0
                )
        return created

    async def expand_node(
        self,
        db: AsyncSession,
        llm_config_id: str,
        node_id: str,
        params: dict | None = None,
    ) -> list[OutlineNode]:
        params = params or {}
        node = await db.get(OutlineNode, node_id)
        if not node:
            return []
        prompt_values = await system_prompt_service.get_effective_values(
            db,
            [
                OUTLINE_EXPAND_SYSTEM_KEY,
                OUTLINE_EXPAND_DEFAULT_COUNT_KEY,
                OUTLINE_EXPAND_TEMPERATURE_KEY,
            ],
        )
        system_prompt = (
            params.get("system_prompt")
            or prompt_values[OUTLINE_EXPAND_SYSTEM_KEY]
        )
        count = self._parse_expand_count(
            params.get("count", prompt_values[OUTLINE_EXPAND_DEFAULT_COUNT_KEY])
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": OUTLINE_EXPAND_USER.format(
                    parent_type=node.node_type,
                    parent_title=node.title,
                    parent_summary=node.summary or "",
                    siblings_info=params.get("siblings_info", "无"),
                    expand_request=params.get("request", "请自然扩展"),
                    count=count,
                ),
            },
        ]
        response = await llm_orchestrator.chat(
            llm_config_id,
            messages,
            temperature=float(prompt_values[OUTLINE_EXPAND_TEMPERATURE_KEY]),
            **json_object_response_kwargs(),
        )
        children_data = json.loads(response)
        created = []
        start_order = await self._get_next_sort_order(db, node.outline_id, node_id)
        for idx, cd in enumerate(
            children_data
            if isinstance(children_data, list)
            else children_data.get("children", [])
        ):
            child = OutlineNode(
                outline_id=node.outline_id,
                parent_id=node_id,
                node_type=cd.get("node_type", "SCENE"),
                title=cd.get("title", ""),
                summary=cd.get("summary", ""),
                sort_order=start_order + idx,
                metadata_=cd.get("metadata"),
                llm_generated=True,
            )
            db.add(child)
            created.append(child)
        await db.commit()
        return created

    @staticmethod
    def _parse_expand_count(value) -> int:
        try:
            count = int(value)
        except (TypeError, ValueError):
            count = 3
        return max(1, min(count, 100))

    async def optimize_outline(
        self,
        db: AsyncSession,
        llm_config_id: str,
        outline_id: str,
        direction: str = "",
    ) -> dict:
        tree_data = await self.get_tree(db, outline_id)
        if not tree_data:
            return {}
        prompt_values = await system_prompt_service.get_effective_values(
            db,
            [
                OUTLINE_OPTIMIZE_SYSTEM_KEY,
                OUTLINE_OPTIMIZE_DEFAULT_DIRECTION_KEY,
                OUTLINE_OPTIMIZE_TEMPERATURE_KEY,
            ],
        )
        optimize_direction = (
            direction or prompt_values[OUTLINE_OPTIMIZE_DEFAULT_DIRECTION_KEY]
        )
        messages = [
            {"role": "system", "content": prompt_values[OUTLINE_OPTIMIZE_SYSTEM_KEY]},
            {
                "role": "user",
                "content": (
                    "请分析并优化以下大纲：\n\n"
                    f"{json.dumps(tree_data, ensure_ascii=False, indent=2, default=str)}"
                    f"\n\n优化方向：{optimize_direction}"
                ),
            },
        ]
        response = await llm_orchestrator.chat(
            llm_config_id,
            messages,
            temperature=float(prompt_values[OUTLINE_OPTIMIZE_TEMPERATURE_KEY]),
            **json_object_response_kwargs(),
        )
        return json.loads(response)

    async def structure_outline(
        self,
        db: AsyncSession,
        llm_config_id: str,
        outline_id: str,
        params: dict | None = None,
    ) -> list[OutlineNode] | None:
        tree_data = await self.get_tree(db, outline_id)
        if not tree_data:
            return None
        params = params or {}
        volume_count = self._parse_expand_count(params.get("volume_count", 3))
        chapters_per_volume = self._parse_expand_count(
            params.get("chapters_per_volume", 10)
        )
        requirements = params.get("requirements") or "请自然整理为分卷分章结构"
        outline_json = json.dumps(
            tree_data,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        messages = [
            {"role": "system", "content": OUTLINE_STRUCTURE_SYSTEM},
            {
                "role": "user",
                "content": OUTLINE_STRUCTURE_USER.format(
                    outline_json=outline_json,
                    volume_count=volume_count,
                    chapters_per_volume=chapters_per_volume,
                    requirements=requirements,
                ),
            },
        ]
        temperature = await system_prompt_service.get_effective_float(
            db, OUTLINE_GENERATE_TEMPERATURE_KEY
        )
        response = await llm_orchestrator.chat(
            llm_config_id,
            messages,
            temperature=temperature,
            **json_object_response_kwargs(),
        )
        nodes_data = self._normalize_structured_outline(json.loads(response))
        if not nodes_data:
            return []

        start_order = await self._get_next_sort_order(db, outline_id, None)
        created = await self._save_nodes_recursive(
            db, outline_id, None, nodes_data, start_order
        )
        await db.commit()
        for node in created:
            await db.refresh(node)
        return created

    @staticmethod
    def _safe_node_type(value, default: str) -> str:
        node_type = str(value or default).upper()
        return node_type if node_type in ALLOWED_NODE_TYPES else default

    def _normalize_structured_outline(self, payload) -> list[dict]:
        if isinstance(payload, list):
            raw_nodes = payload
        elif isinstance(payload, dict):
            raw_nodes = payload.get("children", [])
        else:
            raw_nodes = []
        if not isinstance(raw_nodes, list):
            return []

        volumes = []
        loose_chapters = []
        for raw_node in raw_nodes:
            if not isinstance(raw_node, dict):
                continue
            node_type = self._safe_node_type(raw_node.get("node_type"), "VOLUME")
            if node_type == "VOLUME":
                volumes.append(self._normalize_outline_node(raw_node, "VOLUME"))
            else:
                loose_chapters.append(self._normalize_outline_node(raw_node, "CHAPTER"))

        if loose_chapters:
            volumes.append(
                {
                    "node_type": "VOLUME",
                    "title": "AI 分卷",
                    "summary": "根据现有大纲自动整理的章节安排。",
                    "metadata": {},
                    "children": loose_chapters,
                }
            )
        return volumes

    def _normalize_outline_node(self, raw_node: dict, default_type: str) -> dict:
        node_type = self._safe_node_type(raw_node.get("node_type"), default_type)
        if default_type == "VOLUME" and node_type != "VOLUME":
            node_type = "VOLUME"
        if default_type == "CHAPTER" and node_type == "VOLUME":
            node_type = "CHAPTER"
        title = str(raw_node.get("title") or "未命名节点").strip() or "未命名节点"
        summary = str(raw_node.get("summary") or "").strip()
        metadata = raw_node.get("metadata")
        children = raw_node.get("children")
        if children is None and isinstance(raw_node.get("chapters"), list):
            children = raw_node.get("chapters")
        normalized_children = []
        if isinstance(children, list):
            normalized_children = [
                self._normalize_outline_node(child, "CHAPTER")
                for child in children
                if isinstance(child, dict)
            ]
        return {
            "node_type": node_type,
            "title": title,
            "summary": summary,
            "metadata": metadata if isinstance(metadata, dict) else {},
            "children": normalized_children,
        }

    async def add_node(
        self, db: AsyncSession, data: OutlineNodeCreate
    ) -> OutlineNode:
        sort_order = (
            data.sort_order
            if data.sort_order is not None
            else await self._get_next_sort_order(db, data.outline_id, data.parent_id)
        )
        node = OutlineNode(
            outline_id=data.outline_id,
            parent_id=data.parent_id,
            node_type=data.node_type,
            title=data.title,
            summary=data.summary,
            sort_order=sort_order,
            metadata_=data.metadata,
            llm_generated=False,
        )
        db.add(node)
        await db.flush()
        if data.sort_order is not None:
            await self._normalize_sibling_order(
                db, data.outline_id, data.parent_id, node, data.sort_order
            )
        await db.commit()
        await db.refresh(node)
        return node

    async def update_node(
        self, db: AsyncSession, node_id: str, data: OutlineNodeUpdate
    ) -> OutlineNode | None:
        node = await db.get(OutlineNode, node_id)
        if not node:
            return None
        update_data = data.model_dump(exclude_unset=True)
        if "metadata" in update_data:
            update_data["metadata_"] = update_data.pop("metadata")
        for key, value in update_data.items():
            setattr(node, key, value)
        await db.commit()
        await db.refresh(node)
        return node

    async def move_node(
        self,
        db: AsyncSession,
        node_id: str,
        new_parent_id: str | None,
        new_order: int,
    ) -> OutlineNode | None:
        node = await db.get(OutlineNode, node_id)
        if not node:
            return None
        if new_parent_id:
            new_parent = await db.get(OutlineNode, new_parent_id)
            if not new_parent or new_parent.outline_id != node.outline_id:
                return None
        old_parent_id = node.parent_id
        node.parent_id = new_parent_id
        await db.flush()
        if old_parent_id != new_parent_id:
            await self._normalize_sibling_order(db, node.outline_id, old_parent_id)
        await self._normalize_sibling_order(
            db, node.outline_id, new_parent_id, node, new_order
        )
        await db.commit()
        await db.refresh(node)
        return node

    async def delete_node(self, db: AsyncSession, node_id: str) -> bool:
        node = await db.get(OutlineNode, node_id)
        if not node:
            return False
        await db.delete(node)
        await db.commit()
        return True


outline_service = OutlineService()
