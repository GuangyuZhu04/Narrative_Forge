import json
import os

import pytest

os.environ["DEBUG"] = "false"

from app.core.security import encrypt_api_key  # noqa: E402
from app.llm.providers.base import (  # noqa: E402
    LLMContentFilteredError,
    LLMOutputTruncatedError,
    LLMStreamProtocolError,
)
from app.llm.providers.deepseek import DeepSeekProvider  # noqa: E402
from app.llm.providers.openai import OpenAIProvider  # noqa: E402


def _config(provider: str, model: str, base_url: str) -> dict:
    return {
        "provider": provider,
        "api_key_encrypted": encrypt_api_key("sk-test"),
        "model_name": model,
        "base_url": base_url,
        "default_params": {},
    }


class _FakeStreamResponse:
    def __init__(self, lines: list[str]):
        self.lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self.lines:
            yield line


class _FakeAsyncClient:
    def __init__(self, lines: list[str], requests: list[dict] | None = None):
        self.lines = lines
        self.requests = requests

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, *args, **kwargs):
        if self.requests is not None:
            self.requests.append({"args": args, "kwargs": kwargs})
        return _FakeStreamResponse(self.lines)


def _patch_stream_client(
    monkeypatch,
    provider_module,
    events: list[dict],
    requests: list[dict] | None = None,
) -> None:
    lines = [f"data: {json.dumps(event)}" for event in events]
    monkeypatch.setattr(
        provider_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(lines, requests),
    )


@pytest.mark.anyio
async def test_openai_stream_emits_usage_and_requires_completed(monkeypatch):
    from app.llm.providers import openai as openai_module

    provider = OpenAIProvider(
        _config("openai", "gpt-5.5", "https://api.openai.com/v1")
    )
    _patch_stream_client(
        monkeypatch,
        openai_module,
        [
            {"type": "response.output_text.delta", "delta": "chapter"},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_1",
                    "model": "gpt-5.5",
                    "status": "completed",
                    "output": [],
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 5,
                        "input_tokens_details": {"cached_tokens": 15},
                        "output_tokens_details": {"reasoning_tokens": 2},
                    },
                },
            },
        ],
    )

    events = [
        event
        async for event in provider.stream_completion_events(
            [{"role": "user", "content": "write"}]
        )
    ]

    assert events[0] == {"type": "content", "content": "chapter"}
    assert events[1]["type"] == "usage"
    assert events[1]["usage"]["cached_input_tokens"] == 15
    assert events[1]["usage"]["reasoning_tokens"] == 2


@pytest.mark.anyio
async def test_openai_stream_incomplete_max_tokens_raises(monkeypatch):
    from app.llm.providers import openai as openai_module

    provider = OpenAIProvider(
        _config("openai", "gpt-5.5", "https://api.openai.com/v1")
    )
    _patch_stream_client(
        monkeypatch,
        openai_module,
        [
            {
                "type": "response.incomplete",
                "response": {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                },
            }
        ],
    )

    with pytest.raises(LLMOutputTruncatedError):
        async for _ in provider.stream_completion_events(
            [{"role": "user", "content": "write"}]
        ):
            pass


@pytest.mark.anyio
async def test_openai_stream_eof_without_terminal_raises(monkeypatch):
    from app.llm.providers import openai as openai_module

    provider = OpenAIProvider(
        _config("openai", "gpt-5.5", "https://api.openai.com/v1")
    )
    _patch_stream_client(
        monkeypatch,
        openai_module,
        [{"type": "response.output_text.delta", "delta": "partial"}],
    )

    with pytest.raises(LLMStreamProtocolError):
        async for _ in provider.stream_completion_events(
            [{"role": "user", "content": "write"}]
        ):
            pass


@pytest.mark.anyio
async def test_deepseek_v4_pro_streams_from_responses_endpoint(monkeypatch):
    from app.llm.providers import deepseek as deepseek_module

    provider = DeepSeekProvider(
        _config("deepseek", "deepseek-v4-pro", "https://api.deepseek.com")
    )
    requests: list[dict] = []
    _patch_stream_client(
        monkeypatch,
        deepseek_module,
        [
            {"type": "response.reasoning_text.delta", "delta": "思考"},
            {"type": "response.output_text.delta", "delta": "正文"},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_pro_stream",
                    "model": "deepseek-v4-pro",
                    "status": "completed",
                    "output": [],
                    "usage": {
                        "input_tokens": 8,
                        "output_tokens": 3,
                        "input_tokens_details": {"cached_tokens": 5},
                        "output_tokens_details": {"reasoning_tokens": 1},
                    },
                },
            },
        ],
        requests,
    )

    events = [
        event
        async for event in provider.stream_completion_events(
            [{"role": "user", "content": "write"}],
            max_tokens=123,
        )
    ]

    assert requests[0]["args"][:2] == (
        "POST",
        "https://api.deepseek.com/responses",
    )
    assert requests[0]["kwargs"]["json"]["max_output_tokens"] == 123
    assert events[0] == {"type": "thinking", "content": "思考"}
    assert events[1] == {"type": "content", "content": "正文"}
    assert events[2]["type"] == "usage"
    assert events[2]["usage"]["cached_input_tokens"] == 5
    assert events[2]["usage"]["reasoning_tokens"] == 1


@pytest.mark.anyio
async def test_deepseek_stream_incomplete_content_filter_raises(monkeypatch):
    from app.llm.providers import deepseek as deepseek_module

    provider = DeepSeekProvider(
        _config("deepseek", "deepseek-v4-flash", "https://api.deepseek.com")
    )
    _patch_stream_client(
        monkeypatch,
        deepseek_module,
        [
            {
                "type": "response.incomplete",
                "response": {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "content_filter"},
                },
            }
        ],
    )

    with pytest.raises(LLMContentFilteredError):
        async for _ in provider.stream_completion_events(
            [{"role": "user", "content": "write"}]
        ):
            pass


@pytest.mark.anyio
async def test_deepseek_responses_stream_eof_without_terminal_raises(monkeypatch):
    from app.llm.providers import deepseek as deepseek_module

    provider = DeepSeekProvider(
        _config("deepseek", "deepseek-v4-flash", "https://api.deepseek.com")
    )
    _patch_stream_client(
        monkeypatch,
        deepseek_module,
        [{"type": "response.output_text.delta", "delta": "partial"}],
    )

    with pytest.raises(LLMStreamProtocolError):
        async for _ in provider.stream_completion_events(
            [{"role": "user", "content": "write"}]
        ):
            pass


@pytest.mark.anyio
async def test_deepseek_responses_stream_error_event_raises_upstream_detail(
    monkeypatch,
):
    from app.llm.providers import deepseek as deepseek_module

    provider = DeepSeekProvider(
        _config("deepseek", "deepseek-v4-pro", "https://api.deepseek.com")
    )
    _patch_stream_client(
        monkeypatch,
        deepseek_module,
        [{"type": "error", "error": {"message": "upstream failed"}}],
    )

    with pytest.raises(RuntimeError, match="upstream failed"):
        async for _ in provider.stream_completion_events(
            [{"role": "user", "content": "write"}]
        ):
            pass


@pytest.mark.anyio
async def test_deepseek_chat_stream_resource_interruption_is_failure(monkeypatch):
    from app.llm.providers import deepseek as deepseek_module

    provider = DeepSeekProvider(
        _config("deepseek", "deepseek-v4-pro", "https://api.deepseek.com")
    )
    _patch_stream_client(
        monkeypatch,
        deepseek_module,
        [
            {
                "id": "chat_1",
                "model": "deepseek-v4-pro",
                "choices": [
                    {
                        "delta": {"content": "partial chapter"},
                        "finish_reason": "insufficient_system_resource",
                    }
                ],
            }
        ],
    )

    with pytest.raises(RuntimeError, match="insufficient_system_resource"):
        async for _ in provider.stream_completion_events(
            [{"role": "user", "content": "write"}],
            api_mode="chat_completions",
            _force_max_thinking=False,
        ):
            pass
