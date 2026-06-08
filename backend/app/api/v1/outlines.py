import json

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, verify_project_access
from app.models.project import Project
from app.services.outline_service import outline_service
from app.schemas.outline import (
    OutlineCreate,
    OutlineUpdate,
    OutlineResponse,
    OutlineNodeCreate,
    OutlineNodeUpdate,
    OutlineNodeMove,
    OutlineNodeResponse,
    OutlineTreeResponse,
    OutlineGenerateRequest,
    OutlineExpandRequest,
    OutlineOptimizeRequest,
)
from app.core.exceptions import OutlineNotFoundException

router = APIRouter()


@router.get("")
async def list_outlines(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    outlines = await outline_service.get_list(db, project_id)
    return {
        "data": [OutlineResponse.model_validate(o).model_dump() for o in outlines]
    }


@router.get("/{outline_id}/tree", response_model=OutlineTreeResponse)
async def get_outline_tree(
    project_id: str,
    outline_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    result = await outline_service.get_tree(db, outline_id)
    if not result:
        raise OutlineNotFoundException()
    return result


@router.post("", response_model=OutlineResponse, status_code=201)
async def create_outline(
    project_id: str,
    data: OutlineCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    outline = await outline_service.create(db, project_id, data)
    return outline


@router.put("/{outline_id}", response_model=OutlineResponse)
async def update_outline(
    project_id: str,
    outline_id: str,
    data: OutlineUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    outline = await outline_service.update(db, outline_id, data)
    if not outline:
        raise OutlineNotFoundException()
    return outline


@router.post("/generate", response_model=OutlineResponse, status_code=201)
async def generate_outline(
    project_id: str,
    data: OutlineGenerateRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    outline = await outline_service.generate_outline(
        db, data.llm_config_id, project_id, data.params
    )
    return outline


@router.post("/nodes/{node_id}/expand", status_code=201)
async def expand_node(
    project_id: str,
    node_id: str,
    data: OutlineExpandRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    nodes = await outline_service.expand_node(
        db, data.llm_config_id, node_id, data.params
    )
    return {
        "data": [OutlineNodeResponse.model_validate(n).model_dump() for n in nodes]
    }


@router.post("/{outline_id}/optimize")
async def optimize_outline(
    project_id: str,
    outline_id: str,
    data: OutlineOptimizeRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    result = await outline_service.optimize_outline(
        db, data.llm_config_id, outline_id, data.direction
    )
    return result


@router.post("/nodes", response_model=OutlineNodeResponse, status_code=201)
async def add_node(
    project_id: str,
    data: OutlineNodeCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    node = await outline_service.add_node(db, data)
    return node


@router.put("/nodes/{node_id}", response_model=OutlineNodeResponse)
async def update_node(
    project_id: str,
    node_id: str,
    data: OutlineNodeUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    node = await outline_service.update_node(db, node_id, data)
    if not node:
        raise OutlineNotFoundException()
    return node


@router.put("/nodes/{node_id}/move", response_model=OutlineNodeResponse)
async def move_node(
    project_id: str,
    node_id: str,
    data: OutlineNodeMove,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    node = await outline_service.move_node(
        db, node_id, data.new_parent_id, data.new_order
    )
    if not node:
        raise OutlineNotFoundException()
    return node


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(
    project_id: str,
    node_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    deleted = await outline_service.delete_node(db, node_id)
    if not deleted:
        raise OutlineNotFoundException()
