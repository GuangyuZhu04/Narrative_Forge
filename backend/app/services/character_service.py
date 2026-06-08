import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character, CharacterRelationship
from app.schemas.character import (
    CharacterCreate,
    CharacterUpdate,
    RelationshipCreate,
    RelationshipUpdate,
)
from app.services.llm_orchestrator import llm_orchestrator
from app.llm.prompts.chapter import (
    CHARACTER_GENERATE_SYSTEM,
    CHARACTER_GENERATE_USER,
    CHARACTER_IMPORT_USER,
)
from app.services.system_prompt_service import (
    CHARACTER_GENERATE_TEMPERATURE_KEY,
    CHARACTER_IMPORT_SYSTEM_KEY,
    CHARACTER_IMPORT_TEMPERATURE_KEY,
    system_prompt_service,
)

CHARACTER_IMPORT_MAX_TOKENS = 8192 * 2


class CharacterService:
    @staticmethod
    def _extract_json(text: str):
        text = text.strip()
        if text.startswith("```"):
            first_newline = text.index("\n") if "\n" in text else len(text)
            text = text[first_newline + 1:]
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
                raise ValueError(f"Cannot extract JSON from LLM response: {text[:200]}")
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "[" or text[i] == "{":
                    depth += 1
                elif text[i] == "]" or text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        return json.loads(text[start : i + 1])
            return json.loads(text[start:])

    async def get_list(
        self, db: AsyncSession, project_id: str
    ) -> list[Character]:
        result = await db.execute(
            select(Character)
            .where(Character.project_id == project_id)
            .order_by(Character.sort_order, Character.created_at, Character.id)
        )
        return list(result.scalars().all())

    async def get_by_id(
        self, db: AsyncSession, character_id: str
    ) -> Character | None:
        return await db.get(Character, character_id)

    async def create(self, db: AsyncSession, project_id: str, data: CharacterCreate) -> Character:
        sort_order = await self._get_next_sort_order(db, project_id)
        character = Character(
            project_id=project_id,
            name=data.name,
            aliases=data.aliases,
            avatar_url=data.avatar_url,
            basic_info=data.basic_info,
            personality=data.personality,
            growth_arc=data.growth_arc,
            biography=data.biography,
            setting_collection=data.setting_collection,
            notes=data.notes,
            sort_order=sort_order,
        )
        db.add(character)
        await db.commit()
        await db.refresh(character)
        return character

    async def update(
        self, db: AsyncSession, character_id: str, data: CharacterUpdate
    ) -> Character | None:
        character = await db.get(Character, character_id)
        if not character:
            return None
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(character, key, value)
        await db.commit()
        await db.refresh(character)
        return character

    async def delete(self, db: AsyncSession, character_id: str) -> bool:
        character = await db.get(Character, character_id)
        if not character:
            return False
        await db.delete(character)
        await db.commit()
        return True

    async def generate_profile(
        self,
        db: AsyncSession,
        llm_config_id: str,
        project_id: str,
        description: str,
    ) -> Character:
        messages = [
            {"role": "system", "content": CHARACTER_GENERATE_SYSTEM},
            {
                "role": "user",
                "content": CHARACTER_GENERATE_USER.format(
                    description=description
                ),
            },
        ]
        temperature = await system_prompt_service.get_effective_float(
            db, CHARACTER_GENERATE_TEMPERATURE_KEY
        )
        response = await llm_orchestrator.chat(
            llm_config_id, messages, temperature=temperature
        )
        profile_data = self._extract_json(response)
        sort_order = await self._get_next_sort_order(db, project_id)
        character = Character(
            project_id=project_id,
            name=profile_data.get("name", "未命名"),
            aliases=profile_data.get("aliases"),
            basic_info=profile_data.get("basic_info"),
            personality=profile_data.get("personality"),
            growth_arc=profile_data.get("growth_arc"),
            biography=profile_data.get("biography"),
            setting_collection=profile_data.get("setting_collection"),
            notes=profile_data.get("notes"),
            sort_order=sort_order,
        )
        db.add(character)
        await db.commit()
        await db.refresh(character)
        return character

    async def import_from_text(
        self,
        db: AsyncSession,
        llm_config_id: str,
        project_id: str,
        text_content: str,
    ) -> list[Character]:
        system_prompt = await system_prompt_service.get_effective_value(
            db, CHARACTER_IMPORT_SYSTEM_KEY
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": CHARACTER_IMPORT_USER.format(
                    text_content=text_content
                ),
            },
        ]
        response = await llm_orchestrator.chat(
            llm_config_id,
            messages,
            temperature=await system_prompt_service.get_effective_float(
                db, CHARACTER_IMPORT_TEMPERATURE_KEY
            ),
            max_tokens=CHARACTER_IMPORT_MAX_TOKENS,
        )
        profile_data = self._extract_json(response)

        if isinstance(profile_data, dict):
            profile_data = [profile_data]

        created = []
        next_sort_order = await self._get_next_sort_order(db, project_id)
        for index, pd_item in enumerate(profile_data):
            character = Character(
                project_id=project_id,
                name=pd_item.get("name", "未命名"),
                aliases=pd_item.get("aliases"),
                basic_info=pd_item.get("basic_info"),
                personality=pd_item.get("personality"),
                growth_arc=pd_item.get("growth_arc"),
                biography=pd_item.get("biography"),
                setting_collection=pd_item.get("setting_collection"),
                notes=pd_item.get("notes"),
                sort_order=next_sort_order + index,
            )
            db.add(character)
            created.append(character)
        await db.commit()
        for c in created:
            await db.refresh(c)
        return created

    async def move(
        self,
        db: AsyncSession,
        project_id: str,
        character_id: str,
        new_order: int,
    ) -> list[Character] | None:
        characters = await self.get_list(db, project_id)
        moving_index = next(
            (index for index, c in enumerate(characters) if c.id == character_id),
            None,
        )
        if moving_index is None:
            return None

        moving = characters.pop(moving_index)
        target_order = max(0, min(new_order, len(characters)))
        characters.insert(target_order, moving)
        for index, character in enumerate(characters):
            character.sort_order = index

        await db.commit()
        return await self.get_list(db, project_id)

    async def _get_next_sort_order(self, db: AsyncSession, project_id: str) -> int:
        result = await db.execute(
            select(func.max(Character.sort_order)).where(
                Character.project_id == project_id
            )
        )
        max_order = result.scalar()
        return (max_order if max_order is not None else -1) + 1

    async def get_relationships(
        self, db: AsyncSession, project_id: str
    ) -> list[dict]:
        result = await db.execute(
            select(CharacterRelationship).where(
                CharacterRelationship.project_id == project_id
            )
        )
        relationships = list(result.scalars().all())
        response_list = []
        for rel in relationships:
            source = await db.get(Character, rel.source_id)
            target = await db.get(Character, rel.target_id)
            rel_dict = {
                "id": rel.id,
                "project_id": rel.project_id,
                "source_id": rel.source_id,
                "target_id": rel.target_id,
                "relationship_type": rel.relationship_type,
                "description": rel.description,
                "intensity": rel.intensity,
                "start_chapter": rel.start_chapter,
                "end_chapter": rel.end_chapter,
                "metadata": rel.metadata_,
                "source_name": source.name if source else None,
                "target_name": target.name if target else None,
            }
            response_list.append(rel_dict)
        return response_list

    async def create_relationship(
        self, db: AsyncSession, project_id: str, data: RelationshipCreate
    ) -> CharacterRelationship:
        relationship = CharacterRelationship(
            project_id=project_id,
            source_id=data.source_id,
            target_id=data.target_id,
            relationship_type=data.relationship_type,
            description=data.description,
            intensity=data.intensity,
            start_chapter=data.start_chapter,
            end_chapter=data.end_chapter,
        )
        db.add(relationship)
        await db.commit()
        await db.refresh(relationship)
        return relationship

    async def update_relationship(
        self, db: AsyncSession, relationship_id: str, data: RelationshipUpdate
    ) -> CharacterRelationship | None:
        rel = await db.get(CharacterRelationship, relationship_id)
        if not rel:
            return None
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(rel, key, value)
        await db.commit()
        await db.refresh(rel)
        return rel

    async def delete_relationship(
        self, db: AsyncSession, relationship_id: str
    ) -> bool:
        rel = await db.get(CharacterRelationship, relationship_id)
        if not rel:
            return False
        await db.delete(rel)
        await db.commit()
        return True


character_service = CharacterService()
