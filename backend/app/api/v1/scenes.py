from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, verify_project_access
from app.llm.providers.base import LLMContentFilteredError, LLMOutputTruncatedError
from app.models.project import Project
from app.schemas.scene import (
    SceneCreate,
    SceneImportRequest,
    SceneMoveRequest,
    SceneResponse,
    SceneUpdate,
)
from app.services.scene_service import SceneImportOutputError, scene_service

router = APIRouter()


def _ensure_project_scene(project_id: str, scene) -> None:
    if not scene or scene.project_id != project_id:
        raise HTTPException(status_code=404, detail="场景不存在")


@router.get("")
async def list_scenes(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    scenes = await scene_service.get_list(db, project_id)
    return {"data": [SceneResponse.model_validate(scene).model_dump() for scene in scenes]}


@router.get("/{scene_id}", response_model=SceneResponse)
async def get_scene(
    project_id: str,
    scene_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    scene = await scene_service.get_by_id(db, scene_id)
    _ensure_project_scene(project_id, scene)
    return scene


@router.post("", response_model=SceneResponse, status_code=201)
async def create_scene(
    project_id: str,
    data: SceneCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    return await scene_service.create(db, project_id, data)


@router.post("/import", status_code=201)
async def import_scenes(
    project_id: str,
    data: SceneImportRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    try:
        scenes = await scene_service.import_from_text(
            db, data.llm_config_id, project_id, data.text_content
        )
    except LLMOutputTruncatedError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "AI 导入场景输出达到模型长度限制，请减少本次导入文本或拆分场景后重试，"
                "也可以提高当前 LLM 配置的 max_tokens。"
            ),
        ) from exc
    except LLMContentFilteredError as exc:
        raise HTTPException(
            status_code=400,
            detail="AI 输出被模型安全策略中断，请调整场景描述文本后重试。",
        ) from exc
    except SceneImportOutputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "data": [SceneResponse.model_validate(scene).model_dump() for scene in scenes],
        "count": len(scenes),
    }


@router.put("/{scene_id}", response_model=SceneResponse)
async def update_scene(
    project_id: str,
    scene_id: str,
    data: SceneUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    scene = await scene_service.get_by_id(db, scene_id)
    _ensure_project_scene(project_id, scene)
    updated = await scene_service.update(db, scene_id, data)
    return updated


@router.delete("/{scene_id}", status_code=204)
async def delete_scene(
    project_id: str,
    scene_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    scene = await scene_service.get_by_id(db, scene_id)
    _ensure_project_scene(project_id, scene)
    await scene_service.delete(db, scene_id)


@router.put("/{scene_id}/move")
async def move_scene(
    project_id: str,
    scene_id: str,
    data: SceneMoveRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    scenes = await scene_service.move(db, project_id, scene_id, data.new_order)
    if scenes is None:
        raise HTTPException(status_code=404, detail="场景不存在")
    return {"data": [SceneResponse.model_validate(scene).model_dump() for scene in scenes]}
