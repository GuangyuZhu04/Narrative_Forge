from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, verify_project_access
from app.llm.providers.base import LLMContentFilteredError, LLMOutputTruncatedError
from app.models.project import Project
from app.services.character_service import character_service
from app.schemas.character import (
    CharacterCreate,
    CharacterUpdate,
    CharacterResponse,
    RelationshipCreate,
    RelationshipUpdate,
    RelationshipResponse,
    CharacterGenerateRequest,
    CharacterImportRequest,
    CharacterMoveRequest,
)
from app.core.exceptions import CharacterNotFoundException

router = APIRouter()

UPLOAD_ROOT = Path("data/uploads")
CHARACTER_IMAGE_ROOT = UPLOAD_ROOT / "characters"
IMAGE_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_CHARACTER_IMAGE_BYTES = 5 * 1024 * 1024


def _avatar_url_to_path(avatar_url: str | None) -> Path | None:
    if not avatar_url or not avatar_url.startswith("/uploads/"):
        return None
    relative_path = avatar_url.removeprefix("/uploads/").lstrip("/")
    path = UPLOAD_ROOT / relative_path
    try:
        path.resolve().relative_to(UPLOAD_ROOT.resolve())
    except ValueError:
        return None
    return path


@router.get("")
async def list_characters(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    characters = await character_service.get_list(db, project_id)
    return {
        "data": [
            CharacterResponse.model_validate(c).model_dump() for c in characters
        ]
    }


@router.get("/{character_id}", response_model=CharacterResponse)
async def get_character(
    project_id: str,
    character_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    character = await character_service.get_by_id(db, character_id)
    if not character:
        raise CharacterNotFoundException()
    return character


@router.post("", response_model=CharacterResponse, status_code=201)
async def create_character(
    project_id: str,
    data: CharacterCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    character = await character_service.create(db, project_id, data)
    return character


@router.put("/{character_id}", response_model=CharacterResponse)
async def update_character(
    project_id: str,
    character_id: str,
    data: CharacterUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    character = await character_service.update(db, character_id, data)
    if not character:
        raise CharacterNotFoundException()
    return character


@router.put("/{character_id}/image", response_model=CharacterResponse)
async def upload_character_image(
    project_id: str,
    character_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    character = await character_service.get_by_id(db, character_id)
    if not character or character.project_id != project_id:
        raise CharacterNotFoundException()

    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    extension = IMAGE_CONTENT_TYPES.get(content_type)
    if not extension:
        raise HTTPException(status_code=400, detail="仅支持 JPG、PNG、WEBP 或 GIF 图片")

    content = await request.body()
    if not content:
        raise HTTPException(status_code=400, detail="图片内容不能为空")
    if len(content) > MAX_CHARACTER_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="图片大小不能超过 5MB")

    upload_dir = CHARACTER_IMAGE_ROOT / project_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    image_path = upload_dir / f"{character_id}_{uuid4().hex}{extension}"
    image_path.write_bytes(content)

    old_image_path = _avatar_url_to_path(character.avatar_url)
    character.avatar_url = f"/uploads/characters/{project_id}/{image_path.name}"
    await db.commit()
    await db.refresh(character)

    if old_image_path and old_image_path.exists() and old_image_path != image_path:
        old_image_path.unlink()
    return character


@router.delete("/{character_id}/image", response_model=CharacterResponse)
async def delete_character_image(
    project_id: str,
    character_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    character = await character_service.get_by_id(db, character_id)
    if not character or character.project_id != project_id:
        raise CharacterNotFoundException()

    image_path = _avatar_url_to_path(character.avatar_url)
    if image_path and image_path.exists():
        image_path.unlink()

    character.avatar_url = None
    await db.commit()
    await db.refresh(character)
    return character


@router.delete("/{character_id}", status_code=204)
async def delete_character(
    project_id: str,
    character_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    character = await character_service.get_by_id(db, character_id)
    if not character or character.project_id != project_id:
        raise CharacterNotFoundException()
    image_path = _avatar_url_to_path(character.avatar_url)

    deleted = await character_service.delete(db, character_id)
    if not deleted:
        raise CharacterNotFoundException()
    if image_path and image_path.exists():
        image_path.unlink()


@router.put("/{character_id}/move")
async def move_character(
    project_id: str,
    character_id: str,
    data: CharacterMoveRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    characters = await character_service.move(
        db, project_id, character_id, data.new_order
    )
    if characters is None:
        raise CharacterNotFoundException()
    return {
        "data": [
            CharacterResponse.model_validate(c).model_dump() for c in characters
        ]
    }


@router.post("/generate", response_model=CharacterResponse, status_code=201)
async def generate_character(
    project_id: str,
    data: CharacterGenerateRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    character = await character_service.generate_profile(
        db, data.llm_config_id, project_id, data.description
    )
    return character


@router.post("/import", status_code=201)
async def import_characters(
    project_id: str,
    data: CharacterImportRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    try:
        characters = await character_service.import_from_text(
            db, data.llm_config_id, project_id, data.text_content
        )
    except LLMOutputTruncatedError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "AI 导入输出达到模型长度限制，请减少本次导入文本、拆分人物后重试，"
                "或提高当前 LLM 配置的 max_tokens。"
            ),
        ) from exc
    except LLMContentFilteredError as exc:
        raise HTTPException(
            status_code=400,
            detail="AI 输出被模型安全策略中断，请调整导入文本后重试。",
        ) from exc
    return {
        "data": [
            CharacterResponse.model_validate(c).model_dump() for c in characters
        ],
        "count": len(characters),
    }


@router.get("/relationships")
async def list_relationships(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    relationships = await character_service.get_relationships(db, project_id)
    return {"data": relationships}


@router.post(
    "/relationships", response_model=RelationshipResponse, status_code=201
)
async def create_relationship(
    project_id: str,
    data: RelationshipCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    relationship = await character_service.create_relationship(db, project_id, data)
    return relationship


@router.put(
    "/relationships/{relationship_id}", response_model=RelationshipResponse
)
async def update_relationship(
    project_id: str,
    relationship_id: str,
    data: RelationshipUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    relationship = await character_service.update_relationship(
        db, relationship_id, data
    )
    if not relationship:
        raise CharacterNotFoundException()
    return relationship


@router.delete("/relationships/{relationship_id}", status_code=204)
async def delete_relationship(
    project_id: str,
    relationship_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    deleted = await character_service.delete_relationship(
        db, relationship_id
    )
    if not deleted:
        raise CharacterNotFoundException()
