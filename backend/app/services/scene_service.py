import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.json_mode import json_object_response_kwargs
from app.llm.prompts.scene import SCENE_IMPORT_USER
from app.models.scene import Scene
from app.schemas.scene import SceneCreate, SceneUpdate
from app.services.llm_orchestrator import llm_orchestrator
from app.services.system_prompt_service import (
    SCENE_IMPORT_SYSTEM_KEY,
    SCENE_IMPORT_TEMPERATURE_KEY,
    system_prompt_service,
)

SCENE_IMPORT_MAX_TOKENS = 8192 * 2


class SceneImportOutputError(ValueError):
    """Raised when scene import returns non-usable structured output."""


class SceneService:
    @staticmethod
    def _text_value(value) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    @staticmethod
    def _extract_json(text: str):
        text = text.strip()
        if not text:
            raise SceneImportOutputError(
                "AI 导入场景未返回内容，请稍后重试，或调整场景描述后再试。"
            )
        if text.startswith("```"):
            first_newline = text.index("\n") if "\n" in text else len(text)
            text = text[first_newline + 1 :]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("[")
            if start == -1:
                start = text.find("{")
            if start == -1:
                raise SceneImportOutputError(
                    "AI 导入场景没有返回合法 JSON，请重试或检查系统设置中的场景导入 prompt。"
                )
            depth = 0
            for index in range(start, len(text)):
                if text[index] in ("[", "{"):
                    depth += 1
                elif text[index] in ("]", "}"):
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : index + 1])
                        except json.JSONDecodeError as exc:
                            raise SceneImportOutputError(
                                "AI 导入场景返回了不完整或非法 JSON，请减少导入文本后重试。"
                            ) from exc
            try:
                return json.loads(text[start:])
            except json.JSONDecodeError as exc:
                raise SceneImportOutputError(
                    "AI 导入场景返回了不完整或非法 JSON，请减少导入文本后重试。"
                ) from exc

    async def get_list(self, db: AsyncSession, project_id: str) -> list[Scene]:
        result = await db.execute(
            select(Scene)
            .where(Scene.project_id == project_id)
            .order_by(Scene.sort_order, Scene.created_at, Scene.id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, db: AsyncSession, scene_id: str) -> Scene | None:
        return await db.get(Scene, scene_id)

    async def create(self, db: AsyncSession, project_id: str, data: SceneCreate) -> Scene:
        scene = Scene(
            project_id=project_id,
            name=data.name,
            location=data.location,
            time=data.time,
            atmosphere=data.atmosphere,
            description=data.description,
            details=data.details,
            notes=data.notes,
            sort_order=await self._get_next_sort_order(db, project_id),
        )
        db.add(scene)
        await db.commit()
        await db.refresh(scene)
        return scene

    async def update(
        self, db: AsyncSession, scene_id: str, data: SceneUpdate
    ) -> Scene | None:
        scene = await db.get(Scene, scene_id)
        if not scene:
            return None
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(scene, key, value)
        await db.commit()
        await db.refresh(scene)
        return scene

    async def delete(self, db: AsyncSession, scene_id: str) -> bool:
        scene = await db.get(Scene, scene_id)
        if not scene:
            return False
        await db.delete(scene)
        await db.commit()
        return True

    async def import_from_text(
        self,
        db: AsyncSession,
        llm_config_id: str,
        project_id: str,
        text_content: str,
    ) -> list[Scene]:
        system_prompt = await system_prompt_service.get_effective_value(
            db, SCENE_IMPORT_SYSTEM_KEY
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": SCENE_IMPORT_USER.format(text_content=text_content),
            },
        ]
        response = await llm_orchestrator.chat(
            llm_config_id,
            messages,
            temperature=await system_prompt_service.get_effective_float(
                db, SCENE_IMPORT_TEMPERATURE_KEY
            ),
            max_tokens=SCENE_IMPORT_MAX_TOKENS,
            **json_object_response_kwargs(),
        )
        scene_data = self._extract_json(response)
        if isinstance(scene_data, dict) and isinstance(scene_data.get("scenes"), list):
            scene_data = scene_data["scenes"]
        elif isinstance(scene_data, dict) and isinstance(scene_data.get("data"), list):
            scene_data = scene_data["data"]
        elif isinstance(scene_data, dict) and isinstance(scene_data.get("scene"), dict):
            scene_data = [scene_data["scene"]]
        elif isinstance(scene_data, dict):
            scene_data = [scene_data]
        elif not isinstance(scene_data, list):
            raise SceneImportOutputError(
                "AI 导入场景返回的 JSON 结构不符合要求，需要包含 scenes 数组或场景对象。"
            )

        created = []
        next_sort_order = await self._get_next_sort_order(db, project_id)
        for index, item in enumerate(scene_data):
            if not isinstance(item, dict):
                continue
            name = (
                self._text_value(item.get("name") or item.get("场景名称"))
                or "未命名场景"
            )
            scene = Scene(
                project_id=project_id,
                name=name[:100],
                location=self._text_value(item.get("location") or item.get("地点")),
                time=self._text_value(item.get("time") or item.get("时间")),
                atmosphere=self._text_value(
                    item.get("atmosphere") or item.get("氛围")
                ),
                description=self._text_value(
                    item.get("description") or item.get("描述")
                ),
                details=self._text_value(item.get("details") or item.get("关键细节")),
                notes=self._text_value(item.get("notes") or item.get("备注")),
                sort_order=next_sort_order + index,
            )
            db.add(scene)
            created.append(scene)

        if not created:
            raise SceneImportOutputError(
                "AI 导入场景没有识别出可导入的场景，请补充更具体的场景描述后重试。"
            )

        await db.commit()
        for scene in created:
            await db.refresh(scene)
        return created

    async def move(
        self,
        db: AsyncSession,
        project_id: str,
        scene_id: str,
        new_order: int,
    ) -> list[Scene] | None:
        scenes = await self.get_list(db, project_id)
        moving_index = next(
            (index for index, scene in enumerate(scenes) if scene.id == scene_id),
            None,
        )
        if moving_index is None:
            return None

        moving = scenes.pop(moving_index)
        target_order = max(0, min(new_order, len(scenes)))
        scenes.insert(target_order, moving)
        for index, scene in enumerate(scenes):
            scene.sort_order = index

        await db.commit()
        return await self.get_list(db, project_id)

    async def _get_next_sort_order(self, db: AsyncSession, project_id: str) -> int:
        result = await db.execute(
            select(func.max(Scene.sort_order)).where(Scene.project_id == project_id)
        )
        max_order = result.scalar()
        return (max_order if max_order is not None else -1) + 1


scene_service = SceneService()
