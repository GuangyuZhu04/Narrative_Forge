import asyncio
import os

import pytest

os.environ["DEBUG"] = "false"

from app.core.exceptions import LLMConfigInactiveException  # noqa: E402
from app.core.security import encrypt_api_key  # noqa: E402
from app.api.v1.llm_config import _safe_connection_error  # noqa: E402
from app.llm.contracts import LLMFinishStatus, LLMResult, LLMUsage  # noqa: E402
from app.services.llm_orchestrator import (  # noqa: E402
    LLMOrchestrator,
    PROVIDER_MAP,
)


def _config(model: str, rpm: int = 60) -> dict:
    return {
        "provider": "deepseek",
        "api_key_encrypted": encrypt_api_key("sk-test"),
        "base_url": "https://api.deepseek.com",
        "model_name": model,
        "default_params": {},
        "rate_limit": {"requests_per_minute": rpm},
        "is_active": True,
        "updated_at": "2026-08-09T00:00:00",
    }


@pytest.mark.anyio
async def test_orchestrator_reloads_provider_when_fingerprint_changes(monkeypatch):
    orchestrator = LLMOrchestrator()
    current = _config("deepseek-v4-pro")

    async def fake_fetch(config_id: str):
        return dict(current)

    monkeypatch.setattr(orchestrator, "_fetch_config", fake_fetch)
    first = await orchestrator._load_provider("config-a")
    current["model_name"] = "deepseek-v4-flash"
    second = await orchestrator._load_provider("config-a")

    assert first is not second
    assert second.model == "deepseek-v4-flash"


@pytest.mark.anyio
async def test_orchestrator_does_not_install_snapshot_invalidated_during_fetch(
    monkeypatch,
):
    orchestrator = LLMOrchestrator()
    old_config = _config("deepseek-v4-pro")
    new_config = _config("deepseek-v4-flash")
    first_fetch_started = asyncio.Event()
    release_first_fetch = asyncio.Event()
    fetch_count = 0

    async def racing_fetch(config_id: str):
        nonlocal fetch_count
        fetch_count += 1
        if fetch_count == 1:
            snapshot = dict(old_config)
            first_fetch_started.set()
            await release_first_fetch.wait()
            return snapshot
        return dict(new_config)

    monkeypatch.setattr(orchestrator, "_fetch_config", racing_fetch)
    load_task = asyncio.create_task(orchestrator._load_provider("config-a"))
    await first_fetch_started.wait()

    orchestrator.invalidate("config-a")
    release_first_fetch.set()
    provider = await load_task

    assert fetch_count == 2
    assert provider.model == "deepseek-v4-flash"
    assert orchestrator._providers["config-a"] is provider
    assert "config-a" in orchestrator._load_locks


@pytest.mark.anyio
async def test_orchestrator_uses_per_config_rate_limiters():
    orchestrator = LLMOrchestrator()

    await orchestrator.initialize("config-a", _config("deepseek-v4-pro", rpm=10))
    await orchestrator.initialize("config-b", _config("deepseek-v4-pro", rpm=80))

    assert orchestrator._rate_limiters["config-a"] is not orchestrator._rate_limiters[
        "config-b"
    ]
    assert orchestrator._rate_limiters["config-a"]._rpm == 10
    assert orchestrator._rate_limiters["config-b"]._rpm == 80


@pytest.mark.anyio
async def test_orchestrator_initialize_rejects_inactive_config():
    orchestrator = LLMOrchestrator()
    config = _config("deepseek-v4-pro")
    config["is_active"] = False

    with pytest.raises(LLMConfigInactiveException):
        await orchestrator.initialize("config-a", config)


@pytest.mark.anyio
async def test_orchestrator_invalidate_drops_provider_credentials_and_limiter():
    orchestrator = LLMOrchestrator()
    await orchestrator.initialize("config-a", _config("deepseek-v4-pro"))

    orchestrator.invalidate("config-a")

    assert "config-a" not in orchestrator._providers
    assert "config-a" not in orchestrator._fingerprints
    assert "config-a" not in orchestrator._rate_limiters


@pytest.mark.anyio
async def test_orchestrator_response_is_rich_and_chat_remains_text(monkeypatch):
    class FakeProvider:
        def __init__(self, config):
            self.config = config

        async def response(self, messages, **kwargs):
            return LLMResult(
                text="chapter",
                usage=LLMUsage(input_tokens=10, output_tokens=3),
                finish_status=LLMFinishStatus.COMPLETED,
                response_id="resp_1",
            )

    config = _config("fake-model")
    config["provider"] = "fake"
    orchestrator = LLMOrchestrator()

    async def fake_fetch(config_id: str):
        return dict(config)

    monkeypatch.setitem(PROVIDER_MAP, "fake", FakeProvider)
    monkeypatch.setattr(orchestrator, "_fetch_config", fake_fetch)

    result = await orchestrator.response(
        "config-a", [{"role": "user", "content": "write"}]
    )
    text = await orchestrator.chat(
        "config-a", [{"role": "user", "content": "write"}]
    )

    assert result.text == "chapter"
    assert result.usage.total_tokens == 13
    assert result.response_id == "resp_1"
    assert text == "chapter"


def test_connection_error_redacts_api_keys():
    provider = type("Provider", (), {"api_key": "sk-secret"})()

    message = _safe_connection_error(
        RuntimeError(
            "request https://example.test/models/x?key=sk-secret "
            "x-goog-api-key: sk-secret"
        ),
        provider,
    )

    assert "sk-secret" not in message
    assert "key=****" in message
