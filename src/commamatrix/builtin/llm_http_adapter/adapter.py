# builtin/llm_http_adapter/adapter.py

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator
from typing import Any, TYPE_CHECKING
from urllib.parse import urlparse

import httpx
from httpx import AsyncClient, HTTPError, HTTPStatusError

from ...components.config import ConfigField
from ...components.hook import BeforeLlmCallCtx
from ...components.llm_adapter import (
    LLM,
    LLMAdapter,
    LLMResponse,
    LLMResponseBlock,
    LLMResponseError,
    StreamDelta,
    StreamEnd,
    llms,
)
from .codec import ApiCodec, ApiProtocol

if TYPE_CHECKING:
    from ...core.agent import Agent


openai_api_key = ConfigField[str](
    name="openai_api_key",
    default=lambda: os.getenv("OPENAI_API_KEY", ""),
    description="OpenAI-compatible API key",
)

anthropic_api_key = ConfigField[str](
    name="anthropic_api_key",
    default=lambda: os.getenv("ANTHROPIC_API_KEY", ""),
    description="Anthropic API key",
)

api_base = ConfigField[str](
    name="llm_api_base",
    default=lambda: os.getenv("LLM_API_BASE", ""),
    description="Default API base URL",
)

api_protocol = ConfigField[str](
    name="llm_api_protocol",
    default=ApiProtocol.CHAT_COMPLETIONS.value,
    description="Default API protocol (see ApiProtocol enum for builtin values)",
)

stream_read_timeout = ConfigField[float](
    name="llm_stream_read_timeout",
    default=60.0,
    description="Streaming read timeout in seconds",
)

request_timeout = ConfigField[float](
    name="llm_request_timeout",
    default=300.0,
    description="Non-streaming request timeout in seconds",
)


class LLMHTTPAdapter(LLMAdapter):
    codec_registry = ApiCodec.registry

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        self._client: AsyncClient | None = None

    async def start(self) -> None:
        self._client = AsyncClient()

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _join_url(base: str, endpoint: str) -> str:
        base = base.rstrip("/")
        if "://" not in base:
            base = "https://" + base
        endpoint = endpoint.lstrip("/")
        path = urlparse(base).path
        if path:
            last = path.rsplit("/", 1)[-1]
            if endpoint == last or endpoint.startswith(last + "/"):
                trimmed = endpoint[len(last):].lstrip("/")
                return f"{base}/{trimmed}".rstrip("/")
        return f"{base}/{endpoint}"

    def _resolve_codec(self, protocol: str) -> ApiCodec:
        try:
            return self.codec_registry[protocol]
        except KeyError:
            raise RuntimeError(f"No codec registered for protocol: {protocol}")

    @staticmethod
    def _resolve_model(ctx: BeforeLlmCallCtx) -> LLM | str:
        if ctx.run.model is None:
            raise RuntimeError("No LLM selected for the current run")
        return ctx.run.model

    def _resolve_api_base(self, ctx: BeforeLlmCallCtx) -> str:
        return ctx.api_base or self.config.get(api_base)

    def _resolve_protocol(self, ctx: BeforeLlmCallCtx) -> ApiProtocol:
        if ctx.api_protocol:
            try:
                return ApiProtocol(ctx.api_protocol)
            except ValueError:
                pass
        return self._detect_protocol(self._resolve_model(ctx))

    def _detect_protocol(self, llm: LLM | str) -> ApiProtocol:
        model_name = llm if isinstance(llm, str) else llm.model_name
        if "claude" in model_name:
            return ApiProtocol.ANTHROPIC_MESSAGES
        return ApiProtocol(self.config.get(api_protocol))

    def _build_headers(self, protocol: ApiProtocol) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if protocol is ApiProtocol.ANTHROPIC_MESSAGES:
            headers["x-api-key"] = self.config.get(anthropic_api_key)
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {self.config.get(openai_api_key)}"
        return headers

    async def ask_llm(self, ctx: BeforeLlmCallCtx, *, stream: bool = False) -> AsyncIterator[StreamDelta | LLMResponseBlock | StreamEnd]:
        effective_model = self._resolve_model(ctx)
        effective_base = self._resolve_api_base(ctx)
        protocol = self._resolve_protocol(ctx)
        codec = self._resolve_codec(protocol)
        headers = self._build_headers(protocol)
        url = self._join_url(effective_base, codec.endpoint)
        body = await codec.build_request(model=effective_model, ctx=ctx)

        actual_stream = stream and codec.can_stream

        if actual_stream:
            body = codec.enable_streaming(body)
            headers["Accept"] = "text/event-stream"
            try:
                async with self._client.stream("POST", url, json=body, headers=headers, timeout=self._stream_timeout) as resp:
                    if resp.status_code >= 400:
                        err_body = (await resp.aread()).decode(errors="replace")
                        print(f"[LLM] ERROR: stream failed ({resp.status_code}): {err_body[:500]}", file=sys.stderr)
                        raise LLMResponseError(f"LLM HTTP stream failed ({resp.status_code}): {err_body}")
                    acc: dict[str, Any] = {}
                    event_count = 0
                    async for etype, data in self._iter_sse_events(resp):
                        event_count += 1
                        result = codec.parse_stream_event(etype, data, acc)
                        if result is not None:
                            yield result
                    blocks, end = codec.flush_stream(acc)
                    for block in blocks:
                        yield block
                    yield end
            except LLMResponseError:
                raise
            except HTTPError as exc:
                print(f"[LLM] ERROR: stream HTTP error: {exc}", file=sys.stderr)
                raise LLMResponseError(f"LLM HTTP stream failed: {exc}") from exc
            except Exception as exc:
                print(f"[LLM] ERROR: unexpected stream error: {type(exc).__name__}: {exc}", file=sys.stderr)
                raise
        else:
            try:
                response = await self._client.post(url, json=body, headers=headers, timeout=self._request_timeout)
                response.raise_for_status()
                payload = response.json()
            except HTTPStatusError as exc:
                err_body = exc.response.text if exc.response else "no response"
                print(f"[LLM] ERROR: request failed ({exc.response.status_code}): {err_body[:500]}", file=sys.stderr)
                raise LLMResponseError(f"LLM HTTP request failed ({exc.response.status_code}): {err_body}") from exc
            except HTTPError as exc:
                print(f"[LLM] ERROR: request HTTP error: {exc}", file=sys.stderr)
                raise LLMResponseError(f"LLM HTTP request failed: {exc}") from exc
            except ValueError as exc:
                print(f"[LLM] ERROR: invalid JSON response: {exc}", file=sys.stderr)
                raise LLMResponseError("LLM returned invalid JSON") from exc

            llm_response = codec.parse_response(payload)
            for block in llm_response.content:
                yield block
            yield StreamEnd(
                stop_reason=llm_response.stop_reason,
                usage=llm_response.usage,
                meta=llm_response.meta,
            )

    @staticmethod
    async def _iter_sse_events(response: httpx.Response) -> AsyncIterator[tuple[str | None, dict[str, Any]]]:
        event_type: str | None = None
        data_lines: list[str] = []

        async for line in response.aiter_lines():
            line = line.rstrip()
            if not line:
                if data_lines:
                    data_str = "\n".join(data_lines)
                    if data_str == "[DONE]":
                        return
                    try:
                        yield event_type, json.loads(data_str)
                    except json.JSONDecodeError:
                        print(f"[LLM] WARNING: failed to parse SSE JSON: {data_str[:200]}", file=sys.stderr)
                    data_lines = []
                event_type = None
                continue

            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())

        if data_lines:
            data_str = "\n".join(data_lines)
            if data_str != "[DONE]":
                try:
                    yield event_type, json.loads(data_str)
                except json.JSONDecodeError:
                    print(f"[LLM] WARNING: trailing SSE JSON parse error: {data_str[:200]}", file=sys.stderr)

    @property
    def _stream_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(connect=10.0, read=self.config.get(stream_read_timeout), write=10.0, pool=10.0)

    @property
    def _request_timeout(self) -> float:
        return self.config.get(request_timeout)
