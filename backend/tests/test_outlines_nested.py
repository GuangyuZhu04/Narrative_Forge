import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ["DEBUG"] = "false"

from app.db.session import get_db  # noqa: E402
from app.llm.json_mode import DEEPSEEK_JSON_OBJECT_RESPONSE_FORMAT  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
import app.services.outline_service as outline_module  # noqa: E402


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        yield test_client

    app.dependency_overrides.pop(get_db, None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def create_project_outline(client):
    project_response = await client.post(
        "/api/v1/projects",
        json={"name": "outline ordering"},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    outline_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines",
        json={"title": "Main outline"},
    )
    assert outline_response.status_code == 201
    outline_id = outline_response.json()["id"]
    return project_id, outline_id


@pytest.mark.anyio
async def test_update_outline_node_returns_serializable_metadata(client):
    project_id, outline_id = await create_project_outline(client)

    node_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "node_type": "VOLUME",
            "title": "Old title",
            "summary": "Old summary",
        },
    )
    assert node_response.status_code == 201
    node_id = node_response.json()["id"]

    update_response = await client.put(
        f"/api/v1/projects/{project_id}/outlines/nodes/{node_id}",
        json={"title": "New title", "summary": None},
    )

    assert update_response.status_code == 200
    data = update_response.json()
    assert data["title"] == "New title"
    assert data["summary"] is None
    assert data["metadata"] is None


@pytest.mark.anyio
async def test_add_outline_child_node_appends_to_last_position(client):
    project_id, outline_id = await create_project_outline(client)

    volume_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "node_type": "VOLUME",
            "title": "Volume",
        },
    )
    assert volume_response.status_code == 201
    volume_id = volume_response.json()["id"]

    created = []
    for title in ("Chapter A", "Chapter B", "Chapter C"):
        response = await client.post(
            f"/api/v1/projects/{project_id}/outlines/nodes",
            json={
                "outline_id": outline_id,
                "parent_id": volume_id,
                "node_type": "CHAPTER",
                "title": title,
            },
        )
        assert response.status_code == 201
        created.append(response.json())

    assert [node["sort_order"] for node in created] == [0, 1, 2]

    tree_response = await client.get(
        f"/api/v1/projects/{project_id}/outlines/{outline_id}/tree"
    )
    assert tree_response.status_code == 200
    children = tree_response.json()["tree"][0]["children"]
    assert [node["title"] for node in children] == [
        "Chapter A",
        "Chapter B",
        "Chapter C",
    ]


@pytest.mark.anyio
async def test_move_outline_node_reorders_siblings(client):
    project_id, outline_id = await create_project_outline(client)

    volume_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "node_type": "VOLUME",
            "title": "Volume",
        },
    )
    assert volume_response.status_code == 201
    volume_id = volume_response.json()["id"]

    nodes = {}
    for title in ("Chapter A", "Chapter B", "Chapter C"):
        response = await client.post(
            f"/api/v1/projects/{project_id}/outlines/nodes",
            json={
                "outline_id": outline_id,
                "parent_id": volume_id,
                "node_type": "CHAPTER",
                "title": title,
            },
        )
        assert response.status_code == 201
        nodes[title] = response.json()

    move_response = await client.put(
        f"/api/v1/projects/{project_id}/outlines/nodes/{nodes['Chapter B']['id']}/move",
        json={"new_parent_id": volume_id, "new_order": 2},
    )
    assert move_response.status_code == 200

    tree_response = await client.get(
        f"/api/v1/projects/{project_id}/outlines/{outline_id}/tree"
    )
    assert tree_response.status_code == 200
    children = tree_response.json()["tree"][0]["children"]
    assert [node["title"] for node in children] == [
        "Chapter A",
        "Chapter C",
        "Chapter B",
    ]
    assert [node["sort_order"] for node in children] == [0, 1, 2]


@pytest.mark.anyio
async def test_outline_ai_json_mode_kwargs(client, monkeypatch):
    project_response = await client.post(
        "/api/v1/projects",
        json={"name": "outline json mode"},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    captured_kwargs = []

    async def fake_chat(config_id, messages, **kwargs):
        captured_kwargs.append(kwargs)
        if len(captured_kwargs) == 1:
            return """
            {
              "title": "AI 大纲",
              "description": "AI 大纲说明",
              "children": [
                {
                  "node_type": "VOLUME",
                  "title": "第一卷",
                  "summary": "第一卷概要",
                  "metadata": {},
                  "children": []
                }
              ]
            }
            """
        if len(captured_kwargs) == 2:
            return """
            {
              "children": [
                {
                  "node_type": "CHAPTER",
                  "title": "第一章",
                  "summary": "第一章概要",
                  "metadata": {}
                }
              ]
            }
            """
        return """
        {
          "issues": [],
          "suggestions": [],
          "optimized_structure": {}
        }
        """

    monkeypatch.setattr(outline_module.llm_orchestrator, "chat", fake_chat)

    generate_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/generate",
        json={"llm_config_id": "test-config", "params": {}},
    )
    assert generate_response.status_code == 201
    outline_id = generate_response.json()["id"]

    tree_response = await client.get(
        f"/api/v1/projects/{project_id}/outlines/{outline_id}/tree"
    )
    assert tree_response.status_code == 200
    volume_id = tree_response.json()["tree"][0]["id"]

    expand_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes/{volume_id}/expand",
        json={"llm_config_id": "test-config", "params": {"count": 1}},
    )
    assert expand_response.status_code == 201

    optimize_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/{outline_id}/optimize",
        json={"llm_config_id": "test-config", "direction": "检查节奏"},
    )
    assert optimize_response.status_code == 200

    assert len(captured_kwargs) == 3
    assert all(
        kwargs["response_format"] == DEEPSEEK_JSON_OBJECT_RESPONSE_FORMAT
        for kwargs in captured_kwargs
    )
