import asyncio
import base64
import binascii
import copy
import hashlib
import io
import json
import re
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import websockets


@dataclass(slots=True)
class AudioResult:
    content: bytes
    extension: str = ".mp3"
    content_type: str = "audio/mpeg"
    task_id: str | None = None
    file_id: str | None = None


class TTSProviderError(RuntimeError):
    pass


class TTSRateLimitError(TTSProviderError):
    pass


TaskStatusCallback = Callable[[str, dict[str, str | None]], Awaitable[None]]


class _RequestRateLimiter:
    def __init__(
        self,
        requests_per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.interval_seconds = 60.0 / requests_per_minute
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._next_allowed_at = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            delay = self._next_allowed_at - now
            if delay > 0:
                await self._sleep(delay)
                now = self._clock()
            self._next_allowed_at = max(now, self._next_allowed_at) + self.interval_seconds


_WEBSOCKET_RATE_LIMITERS: dict[tuple[int, str, str, int], _RequestRateLimiter] = {}


def _shared_websocket_rate_limiter(
    endpoint_url: str,
    api_key: str,
    requests_per_minute: int,
) -> _RequestRateLimiter | None:
    if requests_per_minute <= 0:
        return None
    loop_id = id(asyncio.get_running_loop())
    credential_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    key = (loop_id, endpoint_url, credential_hash, requests_per_minute)
    limiter = _WEBSOCKET_RATE_LIMITERS.get(key)
    if limiter is None:
        limiter = _RequestRateLimiter(requests_per_minute)
        _WEBSOCKET_RATE_LIMITERS[key] = limiter
    return limiter


def _ensure_mp3(content: bytes, service_name: str) -> None:
    has_id3 = content.startswith(b"ID3")
    has_frame_sync = len(content) > 1 and content[0] == 0xFF and content[1] & 0xE0 == 0xE0
    if not (has_id3 or has_frame_sync):
        raise TTSProviderError(f"{service_name} 返回的不是 MP3，请检查输出格式配置")


@dataclass(slots=True)
class _WebSocketSession:
    connection: Any
    websocket: Any
    finish_message: dict[str, Any] | None


class OpenAICompatibleTTSProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        timeout_seconds: int,
    ):
        base = base_url.rstrip("/")
        self.endpoint = base if base.endswith("/audio/speech") else f"{base}/audio/speech"
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    async def synthesize(
        self, text: str, voice: str, speed: float, filename_prefix: str
    ) -> AudioResult:
        headers = {"Accept": "audio/mpeg"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model_name,
            "input": text,
            "voice": voice,
            "response_format": "mp3",
            "speed": speed,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self.endpoint, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500].strip()
            raise TTSProviderError(
                f"TTS 服务返回 {exc.response.status_code}: {detail or '请求失败'}"
            ) from exc
        except httpx.HTTPError as exc:
            raise TTSProviderError(f"无法连接 TTS 服务：{exc}") from exc

        if not response.content:
            raise TTSProviderError("TTS 服务返回了空音频")
        content_type = response.headers.get("content-type", "audio/mpeg").split(";")[0]
        if content_type == "application/json":
            raise TTSProviderError(f"TTS 服务未返回音频：{response.text[:500]}")
        _ensure_mp3(response.content, "TTS 服务")
        return AudioResult(content=response.content)


class CustomHTTPTTSProvider:
    ALLOWED_METHODS = {"GET", "POST", "PUT"}
    ALLOWED_BODY_TYPES = {"json", "form", "multipart"}
    ALLOWED_RESPONSE_TYPES = {"binary", "base64", "url"}

    def __init__(
        self,
        *,
        endpoint_url: str,
        api_key: str,
        model_name: str,
        request_config: dict[str, Any],
        timeout_seconds: int,
    ):
        self.endpoint_url = endpoint_url
        self.api_key = api_key
        self.model_name = model_name
        self.request_config = request_config
        self.timeout_seconds = timeout_seconds

    async def synthesize(
        self, text: str, voice: str, speed: float, filename_prefix: str
    ) -> AudioResult:
        variables = {
            "api_key": self.api_key,
            "text": text,
            "voice": voice,
            "model": self.model_name,
            "speed": speed,
            "filename_prefix": filename_prefix,
        }
        method = str(self.request_config.get("method", "POST")).upper()
        body_type = str(self.request_config.get("body_type", "json")).lower()
        response_config = self.request_config.get("response") or {"type": "binary"}
        if not isinstance(response_config, dict):
            raise TTSProviderError("自定义语音 API 的 response 必须是对象")
        response_type = str(response_config.get("type", "binary")).lower()
        if method not in self.ALLOWED_METHODS:
            raise TTSProviderError(f"自定义语音 API 不支持请求方法 {method}")
        if body_type not in self.ALLOWED_BODY_TYPES:
            raise TTSProviderError(f"自定义语音 API 不支持请求体类型 {body_type}")
        if response_type not in self.ALLOWED_RESPONSE_TYPES:
            raise TTSProviderError(f"自定义语音 API 不支持响应类型 {response_type}")

        headers_value = self._render(self.request_config.get("headers") or {}, variables)
        query_value = self._render(self.request_config.get("query") or {}, variables)
        body_value = self._render(self.request_config.get("body") or {}, variables)
        if not all(isinstance(item, dict) for item in (headers_value, query_value, body_value)):
            raise TTSProviderError("自定义语音 API 的 headers、query 和 body 必须是对象")
        headers = {str(key): str(value) for key, value in headers_value.items()}
        if body_type == "multipart":
            headers = {
                key: value for key, value in headers.items() if key.lower() != "content-type"
            }
        request_kwargs: dict[str, Any] = {"headers": headers, "params": query_value}
        if method != "GET":
            if body_type == "json":
                request_kwargs["json"] = body_value
            elif body_type == "form":
                request_kwargs["data"] = body_value
            else:
                request_kwargs["files"] = {
                    str(key): (None, str(value)) for key, value in body_value.items()
                }

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, follow_redirects=True
            ) as client:
                response = await client.request(method, self.endpoint_url, **request_kwargs)
                response.raise_for_status()
                content = await self._extract_audio(
                    client, response, response_type, response_config, variables
                )
        except TTSProviderError:
            raise
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500].strip()
            raise TTSProviderError(
                f"自定义语音 API 返回 {exc.response.status_code}: {detail or '请求失败'}"
            ) from exc
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            raise TTSProviderError(f"自定义语音 API 调用失败：{exc}") from exc

        if not content:
            raise TTSProviderError("自定义语音 API 返回了空音频")
        _ensure_mp3(content, "自定义语音 API")
        return AudioResult(content=content)

    async def _extract_audio(
        self,
        client: httpx.AsyncClient,
        response: httpx.Response,
        response_type: str,
        response_config: dict[str, Any],
        variables: dict[str, Any],
    ) -> bytes:
        if response_type == "binary":
            return response.content
        try:
            payload = response.json()
        except ValueError as exc:
            raise TTSProviderError("自定义语音 API 应返回 JSON，但响应无法解析") from exc
        value = self._get_path(payload, str(response_config.get("path", "")))
        if not isinstance(value, str) or not value.strip():
            raise TTSProviderError("在自定义语音 API 响应中找不到音频字段")
        if response_type == "base64":
            encoded = (
                value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
            )
            try:
                return base64.b64decode(encoded)
            except (binascii.Error, ValueError) as exc:
                raise TTSProviderError("自定义语音 API 返回的 Base64 音频无效") from exc

        download_headers_value = self._render(
            response_config.get("download_headers") or {}, variables
        )
        download_headers = {str(key): str(item) for key, item in download_headers_value.items()}
        download = await client.get(urljoin(str(response.url), value), headers=download_headers)
        download.raise_for_status()
        return download.content

    @classmethod
    def _render(cls, value: Any, variables: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {key: cls._render(item, variables) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._render(item, variables) for item in value]
        if not isinstance(value, str):
            return copy.deepcopy(value)
        for key, replacement in variables.items():
            placeholder = "{{" + key + "}}"
            if value == placeholder:
                return replacement
            value = value.replace(placeholder, str(replacement))
        return value

    @staticmethod
    def _get_path(payload: Any, path: str) -> Any:
        if not path:
            return payload
        current = payload
        for part in re.findall(r"[^.\[\]]+", path):
            if isinstance(current, list):
                current = current[int(part)]
            elif isinstance(current, dict):
                current = current[part]
            else:
                raise KeyError(part)
        return current


class CustomWebSocketTTSProvider:
    ALLOWED_AUDIO_ENCODINGS = {"hex", "base64"}
    EMPTY_AUDIO_MAX_ATTEMPTS = 4
    EMPTY_AUDIO_RETRY_BASE_SECONDS = 2.0
    DEFAULT_MINIMAX_REQUESTS_PER_MINUTE = 20
    RATE_LIMIT_RETRY_SECONDS = 60.0
    STALE_SESSION_MAX_RETRIES = 1

    def __init__(
        self,
        *,
        endpoint_url: str,
        api_key: str,
        model_name: str,
        request_config: dict[str, Any],
        timeout_seconds: int,
        requests_per_minute: int | None = None,
    ):
        self.endpoint_url = endpoint_url
        self.api_key = api_key
        self.model_name = model_name
        self.request_config = request_config
        self.timeout_seconds = timeout_seconds
        hostname = (urlparse(endpoint_url).hostname or "").lower()
        self.reuse_sessions = hostname.endswith(("minimaxi.com", "minimax.io"))
        self._sessions: dict[tuple[str, float], _WebSocketSession] = {}
        default_rpm = (
            self.DEFAULT_MINIMAX_REQUESTS_PER_MINUTE
            if hostname.endswith(("minimaxi.com", "minimax.io"))
            else 0
        )
        try:
            self.requests_per_minute = max(
                0,
                int(
                    requests_per_minute
                    if requests_per_minute is not None
                    else request_config.get("requests_per_minute", default_rpm)
                ),
            )
        except (TypeError, ValueError) as exc:
            raise TTSProviderError(
                "自定义 WebSocket 语音 API 的 requests_per_minute 必须是整数"
            ) from exc

    async def synthesize(
        self, text: str, voice: str, speed: float, filename_prefix: str
    ) -> AudioResult:
        variables = {
            "api_key": self.api_key,
            "text": text,
            "voice": voice,
            "model": self.model_name,
            "speed": speed,
            "filename_prefix": filename_prefix,
        }
        headers_value = CustomHTTPTTSProvider._render(
            self.request_config.get("headers") or {}, variables
        )
        if not isinstance(headers_value, dict):
            raise TTSProviderError("自定义 WebSocket 语音 API 的 headers 必须是对象")
        headers = {str(key): str(value) for key, value in headers_value.items()}

        start_message = self._render_message("start_message", variables, required=True)
        continue_message = self._render_message("continue_message", variables, required=True)
        rendered_finish_message = self._render_message(
            "finish_message", variables, required=False
        )
        response_config = self.request_config.get("response") or {}
        if not isinstance(response_config, dict):
            raise TTSProviderError("自定义 WebSocket 语音 API 的 response 必须是对象")
        audio_encoding = str(response_config.get("audio_encoding", "hex")).lower()
        if audio_encoding not in self.ALLOWED_AUDIO_ENCODINGS:
            raise TTSProviderError(
                f"自定义 WebSocket 语音 API 不支持音频编码 {audio_encoding}"
            )

        if self.reuse_sessions:
            return await self._synthesize_with_reused_session(
                voice=voice,
                speed=speed,
                headers=headers,
                start_message=start_message,
                continue_message=continue_message,
                finish_message=rendered_finish_message,
                response_config=response_config,
                audio_encoding=audio_encoding,
            )
        return await self._synthesize_with_single_session(
            headers=headers,
            start_message=start_message,
            continue_message=continue_message,
            finish_message=rendered_finish_message,
            response_config=response_config,
            audio_encoding=audio_encoding,
        )

    async def _synthesize_with_reused_session(
        self,
        *,
        voice: str,
        speed: float,
        headers: dict[str, str],
        start_message: dict[str, Any],
        continue_message: dict[str, Any],
        finish_message: dict[str, Any] | None,
        response_config: dict[str, Any],
        audio_encoding: str,
    ) -> AudioResult:
        session_key = (voice, speed)
        rate_limit_retries = 0
        stale_session_retries = 0
        for attempt in range(1, self.EMPTY_AUDIO_MAX_ATTEMPTS + 1):
            session: _WebSocketSession | None = None
            session_was_reused = False
            chunks: list[bytes] = []
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    session = self._sessions.get(session_key)
                    session_was_reused = session is not None
                    if session is None:
                        session = await self._open_session(
                            headers,
                            start_message,
                            finish_message,
                            response_config,
                        )
                        self._sessions[session_key] = session
                    await session.websocket.send(
                        json.dumps(continue_message, ensure_ascii=False)
                    )
                    reusable = await self._receive_audio(
                        session.websocket,
                        response_config,
                        audio_encoding,
                        chunks,
                    )
                    if not reusable:
                        await self._discard_session(session_key, session)
            except TTSRateLimitError:
                if session is not None:
                    await self._discard_session(session_key, session)
                if rate_limit_retries >= 1:
                    raise
                rate_limit_retries += 1
                await asyncio.sleep(self.RATE_LIMIT_RETRY_SECONDS)
                continue
            except TTSProviderError:
                if session is not None:
                    await self._discard_session(session_key, session)
                raise
            except TimeoutError as exc:
                if session is not None:
                    await self._discard_session(session_key, session)
                raise TTSProviderError(
                    f"自定义 WebSocket 语音 API 在 {self.timeout_seconds} 秒内未完成"
                ) from exc
            except (
                OSError,
                ValueError,
                TypeError,
            ) as exc:
                if session is not None:
                    await self._discard_session(session_key, session)
                raise TTSProviderError(
                    f"自定义 WebSocket 语音 API 调用失败：{exc}"
                ) from exc
            except websockets.exceptions.WebSocketException as exc:
                if session is not None:
                    await self._discard_session(session_key, session)
                if (
                    session_was_reused
                    and stale_session_retries < self.STALE_SESSION_MAX_RETRIES
                ):
                    stale_session_retries += 1
                    continue
                raise TTSProviderError(
                    f"自定义 WebSocket 语音 API 调用失败：{exc}"
                ) from exc

            content = b"".join(chunks)
            if content:
                _ensure_mp3(content, "自定义 WebSocket 语音 API")
                return AudioResult(content=content)
            if session is not None:
                await self._discard_session(session_key, session)
            if attempt < self.EMPTY_AUDIO_MAX_ATTEMPTS:
                await asyncio.sleep(
                    self.EMPTY_AUDIO_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                )

        raise TTSProviderError(
            "自定义 WebSocket 语音 API "
            f"连续 {self.EMPTY_AUDIO_MAX_ATTEMPTS} 次返回了空音频"
        )

    async def _synthesize_with_single_session(
        self,
        *,
        headers: dict[str, str],
        start_message: dict[str, Any],
        continue_message: dict[str, Any],
        finish_message: dict[str, Any] | None,
        response_config: dict[str, Any],
        audio_encoding: str,
    ) -> AudioResult:

        for attempt in range(1, self.EMPTY_AUDIO_MAX_ATTEMPTS + 1):
            chunks: list[bytes] = []
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    rate_limiter = _shared_websocket_rate_limiter(
                        self.endpoint_url,
                        self.api_key,
                        self.requests_per_minute,
                    )
                    if rate_limiter is not None:
                        await rate_limiter.acquire()
                    async with websockets.connect(
                        self.endpoint_url,
                        additional_headers=headers,
                        open_timeout=self.timeout_seconds,
                    ) as websocket:
                        try:
                            await self._expect_ack(
                                websocket,
                                self.request_config.get("connect_ack"),
                                response_config,
                                "连接",
                            )
                            await websocket.send(
                                json.dumps(start_message, ensure_ascii=False)
                            )
                            await self._expect_ack(
                                websocket,
                                self.request_config.get("start_ack"),
                                response_config,
                                "任务启动",
                            )
                            await websocket.send(
                                json.dumps(continue_message, ensure_ascii=False)
                            )
                            await self._receive_audio(
                                websocket, response_config, audio_encoding, chunks
                            )
                        finally:
                            if finish_message:
                                try:
                                    await websocket.send(
                                        json.dumps(finish_message, ensure_ascii=False)
                                    )
                                except Exception:
                                    pass
            except TTSProviderError:
                raise
            except TimeoutError as exc:
                raise TTSProviderError(
                    f"自定义 WebSocket 语音 API 在 {self.timeout_seconds} 秒内未完成"
                ) from exc
            except (
                OSError,
                ValueError,
                TypeError,
                websockets.exceptions.WebSocketException,
            ) as exc:
                raise TTSProviderError(
                    f"自定义 WebSocket 语音 API 调用失败：{exc}"
                ) from exc

            content = b"".join(chunks)
            if content:
                _ensure_mp3(content, "自定义 WebSocket 语音 API")
                return AudioResult(content=content)
            if attempt < self.EMPTY_AUDIO_MAX_ATTEMPTS:
                await asyncio.sleep(
                    self.EMPTY_AUDIO_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                )

        raise TTSProviderError(
            "自定义 WebSocket 语音 API "
            f"连续 {self.EMPTY_AUDIO_MAX_ATTEMPTS} 次返回了空音频"
        )

    async def _open_session(
        self,
        headers: dict[str, str],
        start_message: dict[str, Any],
        finish_message: dict[str, Any] | None,
        response_config: dict[str, Any],
    ) -> _WebSocketSession:
        rate_limiter = _shared_websocket_rate_limiter(
            self.endpoint_url,
            self.api_key,
            self.requests_per_minute,
        )
        if rate_limiter is not None:
            await rate_limiter.acquire()
        connection = websockets.connect(
            self.endpoint_url,
            additional_headers=headers,
            open_timeout=self.timeout_seconds,
        )
        websocket = await connection.__aenter__()
        try:
            await self._expect_ack(
                websocket,
                self.request_config.get("connect_ack"),
                response_config,
                "连接",
            )
            await websocket.send(json.dumps(start_message, ensure_ascii=False))
            await self._expect_ack(
                websocket,
                self.request_config.get("start_ack"),
                response_config,
                "任务启动",
            )
        except BaseException:
            await connection.__aexit__(None, None, None)
            raise
        return _WebSocketSession(connection, websocket, finish_message)

    async def _discard_session(
        self,
        session_key: tuple[str, float],
        session: _WebSocketSession,
        *,
        graceful: bool = False,
    ) -> None:
        if self._sessions.get(session_key) is session:
            self._sessions.pop(session_key, None)
        if graceful and session.finish_message:
            try:
                await session.websocket.send(
                    json.dumps(session.finish_message, ensure_ascii=False)
                )
            except Exception:
                pass
        try:
            await session.connection.__aexit__(None, None, None)
        except Exception:
            pass

    async def aclose(self) -> None:
        sessions = list(self._sessions.items())
        self._sessions.clear()
        for session_key, session in sessions:
            await self._discard_session(session_key, session, graceful=True)

    def _render_message(
        self, key: str, variables: dict[str, Any], *, required: bool
    ) -> dict[str, Any] | None:
        value = self.request_config.get(key)
        if value is None and not required:
            return None
        rendered = CustomHTTPTTSProvider._render(value, variables)
        if not isinstance(rendered, dict):
            label = {
                "start_message": "start_message",
                "continue_message": "continue_message",
                "finish_message": "finish_message",
            }[key]
            raise TTSProviderError(f"自定义 WebSocket 语音 API 的 {label} 必须是对象")
        return rendered

    async def _expect_ack(
        self,
        websocket: Any,
        ack_config: Any,
        response_config: dict[str, Any],
        stage: str,
    ) -> None:
        if ack_config is None:
            return
        if not isinstance(ack_config, dict):
            raise TTSProviderError(f"自定义 WebSocket 语音 API 的 {stage}确认配置必须是对象")
        payload = await self._receive_json(websocket)
        self._raise_response_error(payload, response_config)
        path = str(ack_config.get("path", ""))
        expected = ack_config.get("equals")
        try:
            actual = CustomHTTPTTSProvider._get_path(payload, path)
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise TTSProviderError(
                f"自定义 WebSocket 语音 API 的{stage}响应缺少字段 {path or '<root>'}"
            ) from exc
        if actual != expected:
            raise TTSProviderError(
                f"自定义 WebSocket 语音 API {stage}失败："
                f"期望 {path or '<root>'}={expected!r}，实际为 {actual!r}"
            )

    async def _receive_audio(
        self,
        websocket: Any,
        response_config: dict[str, Any],
        audio_encoding: str,
        chunks: list[bytes],
    ) -> bool:
        audio_path = str(response_config.get("audio_path", "data.audio"))
        final_path = str(response_config.get("final_path", "is_final"))
        final_value = response_config.get("final_value", True)
        while True:
            try:
                payload = await self._receive_json(websocket)
            except websockets.exceptions.ConnectionClosedOK:
                return False
            self._raise_response_error(payload, response_config)
            audio_value = self._get_optional_path(payload, audio_path)
            if audio_value not in (None, ""):
                if not isinstance(audio_value, str):
                    raise TTSProviderError(
                        f"自定义 WebSocket 语音 API 的音频字段 {audio_path} 必须是字符串"
                    )
                try:
                    if audio_encoding == "hex":
                        chunks.append(bytes.fromhex(audio_value))
                    else:
                        chunks.append(base64.b64decode(audio_value, validate=True))
                except (binascii.Error, ValueError) as exc:
                    raise TTSProviderError(
                        f"自定义 WebSocket 语音 API 返回的 {audio_encoding} 音频无效"
                    ) from exc
            if self._get_optional_path(payload, final_path) == final_value:
                return True
            final_event_path = str(
                response_config.get("final_event_path", "event")
            )
            final_event_value = response_config.get(
                "final_event_value", "task_finished"
            )
            if self._get_optional_path(payload, final_event_path) == final_event_value:
                return False

    @staticmethod
    async def _receive_json(websocket: Any) -> Any:
        message = await websocket.recv()
        if isinstance(message, bytes):
            try:
                message = message.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise TTSProviderError("自定义 WebSocket 语音 API 返回了非 JSON 二进制消息") from exc
        try:
            payload = json.loads(message)
        except (json.JSONDecodeError, TypeError) as exc:
            raise TTSProviderError("自定义 WebSocket 语音 API 返回了无法解析的 JSON") from exc
        if not isinstance(payload, (dict, list)):
            raise TTSProviderError("自定义 WebSocket 语音 API 返回的 JSON 格式不正确")
        return payload

    @staticmethod
    def _get_optional_path(payload: Any, path: str) -> Any:
        try:
            return CustomHTTPTTSProvider._get_path(payload, path)
        except (KeyError, IndexError, ValueError, TypeError):
            return None

    @classmethod
    def _raise_response_error(
        cls, payload: Any, response_config: dict[str, Any]
    ) -> None:
        failure_event_path = str(
            response_config.get("failure_event_path", "event")
        )
        failure_event_value = response_config.get(
            "failure_event_value", "task_failed"
        )
        failure_event = (
            cls._get_optional_path(payload, failure_event_path) == failure_event_value
        )
        error_code_path = str(
            response_config.get("error_code_path", "base_resp.status_code")
        )
        code = cls._get_optional_path(payload, error_code_path)
        response_error = code is not None and code != response_config.get(
            "success_value", 0
        )
        if not failure_event and not response_error:
            return
        message_paths = [
            str(response_config.get("error_message_path", "")),
            "base_resp.status_msg",
            "data.error_message",
            "error.message",
            "message",
        ]
        message = next(
            (
                value
                for path in message_paths
                if path
                and (value := cls._get_optional_path(payload, path)) not in (None, "")
            ),
            None,
        )
        if message is not None:
            detail = str(message).strip()
        elif response_error:
            detail = f"错误码 {code}"
        else:
            detail = f"事件 {failure_event_value}"
        error_type = (
            TTSRateLimitError
            if code == 1002 or "rate limit exceeded(rpm)" in detail.casefold()
            else TTSProviderError
        )
        raise error_type(f"自定义 WebSocket 语音 API 返回错误：{detail}")


class MiniMaxAsyncTTSProvider:
    """MiniMax asynchronous T2A, one remote task per single-voice segment."""

    MAX_TEXT_CHARACTERS = 50_000
    AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac"}
    CONTENT_TYPES = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".flac": "audio/flac",
    }

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        timeout_seconds: int,
        poll_interval_seconds: float = 2.0,
        output_format: str = "wav",
    ):
        base = base_url.rstrip("/")
        for suffix in ("/t2a_async_v2", "/query/t2a_async_query_v2"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        if base.endswith(("api.minimaxi.com", "api.minimax.io")):
            base = f"{base}/v1"
        self.base_url = base
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        normalized_format = output_format.strip().lower()
        if normalized_format not in {"wav", "mp3"}:
            raise ValueError("MiniMax 异步语音输出格式仅支持 wav 或 mp3")
        self.output_format = normalized_format

    async def synthesize(
        self,
        text: str,
        voice: str,
        speed: float,
        filename_prefix: str,
        *,
        task_status_callback: TaskStatusCallback | None = None,
        resume_task_id: str | None = None,
        resume_file_id: str | None = None,
    ) -> AudioResult:
        if not self.api_key:
            raise TTSProviderError("请先配置 MiniMax API Key")
        deadline = time.monotonic() + self.timeout_seconds
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        request_timeout = min(60.0, max(10.0, float(self.timeout_seconds)))
        try:
            async with httpx.AsyncClient(
                timeout=request_timeout,
                follow_redirects=True,
            ) as client:
                task_id = resume_task_id
                file_id = resume_file_id
                if not file_id:
                    if not task_id:
                        task_id = await self._create_task(
                            client,
                            headers,
                            text,
                            voice,
                            speed,
                        )
                    if task_status_callback:
                        await task_status_callback(
                            "processing", {"task_id": task_id, "file_id": None}
                        )
                    file_id = await self._wait_for_task(client, headers, task_id, deadline)
                if task_status_callback:
                    await task_status_callback(
                        "downloading", {"task_id": task_id, "file_id": file_id}
                    )
                result = await self._download_result(client, headers, file_id)
        except TTSProviderError:
            raise
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500].strip()
            raise TTSProviderError(
                f"MiniMax 异步语音接口返回 {exc.response.status_code}: "
                f"{detail or '请求失败'}"
            ) from exc
        except httpx.HTTPError as exc:
            raise TTSProviderError(f"无法连接 MiniMax 异步语音接口：{exc}") from exc

        result.task_id = task_id
        result.file_id = file_id
        return result

    async def _create_task(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        text: str,
        voice: str,
        speed: float,
    ) -> str:
        if len(text) > self.MAX_TEXT_CHARACTERS:
            raise TTSProviderError(
                "MiniMax 异步语音单次直传文本不能超过 5 万字符；"
                "请调低单次请求最大字符数"
            )
        response = await client.post(
            f"{self.base_url}/t2a_async_v2",
            headers=headers,
            json={
                "model": self.model_name,
                "text": text,
                "language_boost": "Chinese",
                "voice_setting": {
                    "voice_id": voice,
                    "speed": speed,
                    "vol": 1.0,
                    "pitch": 0,
                },
                "audio_setting": {
                    "audio_sample_rate": 32000,
                    "bitrate": 128000,
                    "format": self.output_format,
                    "channel": 1,
                },
            },
        )
        response.raise_for_status()
        payload = self._json_payload(response, "创建任务")
        task_id = str(payload.get("task_id", "")).strip()
        if not task_id:
            raise TTSProviderError("MiniMax 创建异步语音任务后未返回 task_id")
        return task_id

    async def _wait_for_task(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        task_id: str,
        deadline: float,
    ) -> str:
        while time.monotonic() < deadline:
            response = await client.get(
                f"{self.base_url}/query/t2a_async_query_v2",
                headers=headers,
                params={"task_id": task_id},
            )
            response.raise_for_status()
            payload = self._json_payload(response, "查询任务")
            status = str(payload.get("status", "")).strip().lower()
            if status == "success":
                file_id = str(payload.get("file_id", "")).strip()
                if not file_id:
                    raise TTSProviderError(
                        f"MiniMax 异步任务 {task_id} 成功但未返回 file_id"
                    )
                return file_id
            if status in {"failed", "expired"}:
                raise TTSProviderError(
                    f"MiniMax 异步语音任务 {task_id} 已{('失败' if status == 'failed' else '过期')}"
                )
            if status != "processing":
                raise TTSProviderError(
                    f"MiniMax 异步语音任务 {task_id} 返回未知状态：{status or '<empty>'}"
                )
            await asyncio.sleep(self.poll_interval_seconds)
        raise TTSProviderError(
            f"MiniMax 异步语音任务 {task_id} 在 {self.timeout_seconds} 秒内未完成"
        )

    async def _download_result(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        file_id: str,
    ) -> AudioResult:
        metadata_response = await client.get(
            f"{self.base_url}/files/retrieve",
            headers=headers,
            params={"file_id": file_id},
        )
        metadata_response.raise_for_status()
        payload = self._json_payload(metadata_response, "检索文件")
        file_metadata = payload.get("file")
        if not isinstance(file_metadata, dict):
            raise TTSProviderError("MiniMax 文件检索响应缺少 file 对象")
        filename = str(file_metadata.get("filename", "")).strip()
        download_url = str(file_metadata.get("download_url", "")).strip()
        if download_url:
            download_response = await client.get(download_url)
        else:
            download_response = await client.get(
                f"{self.base_url}/files/retrieve_content",
                headers=headers,
                params={"file_id": file_id},
            )
        download_response.raise_for_status()
        if not download_response.content:
            raise TTSProviderError(f"MiniMax 文件 {file_id} 下载结果为空")
        content_type = download_response.headers.get("content-type", "").split(";", 1)[0]
        return self._locate_audio(download_response.content, filename, content_type)

    @classmethod
    def _locate_audio(
        cls,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> AudioResult:
        extension = Path(filename).suffix.lower()
        if extension in cls.AUDIO_EXTENSIONS:
            if extension == ".mp3":
                _ensure_mp3(content, "MiniMax 异步语音接口")
            return AudioResult(
                content=content,
                extension=extension,
                content_type=cls.CONTENT_TYPES[extension],
            )
        if zipfile.is_zipfile(io.BytesIO(content)):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                candidates = sorted(
                    (
                        info
                        for info in archive.infolist()
                        if not info.is_dir()
                        and Path(info.filename).suffix.lower() in cls.AUDIO_EXTENSIONS
                    ),
                    key=lambda info: (
                        0 if Path(info.filename).suffix.lower() == ".wav" else 1,
                        info.filename,
                    ),
                )
                if not candidates:
                    raise TTSProviderError("MiniMax 异步结果压缩包中没有音频文件")
                selected = candidates[0]
                audio = archive.read(selected)
                audio_extension = Path(selected.filename).suffix.lower()
                if audio_extension == ".mp3":
                    _ensure_mp3(audio, "MiniMax 异步语音接口")
                return AudioResult(
                    content=audio,
                    extension=audio_extension,
                    content_type=cls.CONTENT_TYPES[audio_extension],
                )
        if content.startswith(b"RIFF") and content[8:12] == b"WAVE":
            return AudioResult(content=content, extension=".wav", content_type="audio/wav")
        if content.startswith(b"fLaC"):
            return AudioResult(content=content, extension=".flac", content_type="audio/flac")
        if content_type in {"audio/mpeg", "audio/mp3"}:
            _ensure_mp3(content, "MiniMax 异步语音接口")
            return AudioResult(content=content)
        raise TTSProviderError(
            f"MiniMax 异步结果格式不受支持：{filename or content_type or '未知格式'}"
        )

    @staticmethod
    def _json_payload(response: httpx.Response, operation: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise TTSProviderError(f"MiniMax {operation}响应不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise TTSProviderError(f"MiniMax {operation}响应格式不正确")
        base_resp = payload.get("base_resp")
        if not isinstance(base_resp, dict):
            raise TTSProviderError(f"MiniMax {operation}响应缺少 base_resp")
        status_code = base_resp.get("status_code")
        if str(status_code) != "0":
            detail = str(base_resp.get("status_msg", "")).strip() or f"错误码 {status_code}"
            raise TTSProviderError(f"MiniMax {operation}失败：{detail}")
        return payload


class ComfyUITTSProvider:
    AUDIO_EXTENSIONS = {".mp3", ".mpeg", ".mpga"}

    def __init__(
        self,
        *,
        base_url: str,
        workflow: dict[str, Any],
        timeout_seconds: int,
    ):
        self.base_url = base_url.rstrip("/")
        self.workflow = workflow
        self.timeout_seconds = timeout_seconds

    async def synthesize(
        self, text: str, voice: str, speed: float, filename_prefix: str
    ) -> AudioResult:
        prompt = self._render_workflow(
            self.workflow,
            {
                "text": text,
                "voice": voice,
                "speed": speed,
                "filename_prefix": filename_prefix,
            },
        )
        client_id = str(uuid.uuid4())
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                submit = await client.post(
                    f"{self.base_url}/prompt",
                    json={"prompt": prompt, "client_id": client_id},
                )
                submit.raise_for_status()
                prompt_id = submit.json().get("prompt_id")
                if not prompt_id:
                    raise TTSProviderError("ComfyUI 未返回 prompt_id，请确认使用的是 API 工作流")

                output = await self._wait_for_output(client, str(prompt_id))
                audio_info = self._find_audio_info(output)
                if not audio_info:
                    raise TTSProviderError("ComfyUI 工作流已结束，但输出中没有 MP3 文件")
                audio_response = await client.get(
                    f"{self.base_url}/view",
                    params={
                        "filename": audio_info["filename"],
                        "subfolder": audio_info.get("subfolder", ""),
                        "type": audio_info.get("type", "output"),
                    },
                )
                audio_response.raise_for_status()
        except TTSProviderError:
            raise
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500].strip()
            raise TTSProviderError(
                f"ComfyUI 返回 {exc.response.status_code}: {detail or '请求失败'}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise TTSProviderError(f"无法完成 ComfyUI 工作流：{exc}") from exc

        if not audio_response.content:
            raise TTSProviderError("ComfyUI 返回了空音频")
        _ensure_mp3(audio_response.content, "ComfyUI")
        return AudioResult(content=audio_response.content)

    async def _wait_for_output(self, client: httpx.AsyncClient, prompt_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            history_response = await client.get(f"{self.base_url}/history/{prompt_id}")
            history_response.raise_for_status()
            history = history_response.json()
            item = history.get(prompt_id) if isinstance(history, dict) else None
            if item:
                status = item.get("status") or {}
                if status.get("status_str") == "error":
                    messages = status.get("messages") or []
                    raise TTSProviderError(f"ComfyUI 工作流执行失败：{str(messages)[:500]}")
                if item.get("outputs"):
                    return item["outputs"]
            await asyncio.sleep(1)
        raise TTSProviderError(f"ComfyUI 工作流在 {self.timeout_seconds} 秒内没有生成音频")

    @classmethod
    def _render_workflow(cls, value: Any, variables: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {key: cls._render_workflow(item, variables) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._render_workflow(item, variables) for item in value]
        if not isinstance(value, str):
            return copy.deepcopy(value)
        for key, replacement in variables.items():
            placeholder = "{{" + key + "}}"
            if value == placeholder:
                return replacement
            value = value.replace(placeholder, str(replacement))
        return value

    @classmethod
    def _find_audio_info(cls, value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            filename = value.get("filename")
            if isinstance(filename, str):
                extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                if extension in cls.AUDIO_EXTENSIONS:
                    return value
            for item in value.values():
                if result := cls._find_audio_info(item):
                    return result
        elif isinstance(value, list):
            for item in value:
                if result := cls._find_audio_info(item):
                    return result
        return None
