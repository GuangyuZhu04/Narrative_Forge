from pathlib import Path
import sys

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_launcher import DesktopStaticFiles  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_desktop_serves_bundled_ui_and_deep_links_without_swallowing_api(tmp_path):
    (tmp_path / "index.html").write_text('<div id="root">Desktop</div>', encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('desktop')", encoding="utf-8")
    app = FastAPI()

    @app.get("/api/v1/health")
    async def health():
        return {"ok": True}

    app.mount("/", DesktopStaticFiles(directory=tmp_path, html=True))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for route in ("/", "/settings", "/projects/demo/novel", "/projects/demo/chapters/chapter-1"):
            response = await client.get(route)
            assert response.status_code == 200, route
            assert response.headers["content-type"].startswith("text/html")
            assert '<div id="root">' in response.text
        script = await client.get("/assets/app.js")
        assert script.status_code == 200
        assert script.text == "console.log('desktop')"
        assert (await client.get("/api/v1/health")).json() == {"ok": True}
        for route in ("/api/v1/missing", "/uploads/missing.png", "/assets/missing.js"):
            assert (await client.get(route)).status_code == 404
        assert (await client.post("/settings")).status_code == 405
