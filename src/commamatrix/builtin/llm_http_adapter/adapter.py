# builtin/llm_http_adapter/adapter.py

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse

import httpx2 as httpx
from httpx2 import HTTPError, HTTPStatusError

from ...components.config import ConfigField
from ...components.hook import BeforeLlmCallCtx
from ...components.llm_adapter import (
    LLM,
    LLMAdapter,
    LLMResponseBlock,
    LLMResponseError,
    StreamDelta,
    StreamEnd,
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

llm_api_base = ConfigField[str](
    name="llm_api_base",
    default=lambda: os.getenv("LLM_API_BASE", ""),
    description="Default API base URL",
)

llm_api_protocol = ConfigField[str](
    name="llm_api_protocol",
    default=ApiProtocol.CHAT_COMPLETIONS.value,
    description="Default API protocol (see ApiProtocol enum for builtin values)",
)

llm_refresh_on_start = ConfigField[bool](
    name="llm_refresh_on_start",
    default=True,
    description="Refresh available LLMs when the adapter starts",
)

llm_stream_read_timeout = ConfigField[float](
    name="llm_stream_read_timeout",
    default=60.0,
    description="Streaming read timeout in seconds",
)

llm_request_timeout = ConfigField[float](
    name="llm_request_timeout",
    default=300.0,
    description="Non-streaming request timeout in seconds",
)


class LLMHTTPAdapter(LLMAdapter):
    codec_registry = ApiCodec.registry

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)

    @property
    def codec(self) -> ApiCodec:
        return self._resolve_codec(self.config.get(llm_api_protocol))

    async def start(self) -> None:
        if not self.config.get(llm_refresh_on_start):
            self.llms = []
            self.logger.info("LLM model refresh skipped during adapter startup")
            return
        await super().start()

    def _model_headers(self) -> dict[str, str]:
        protocol = ApiProtocol(self.config.get(llm_api_protocol))
        headers = self._build_headers(protocol)
        headers.pop("Content-Type", None)
        headers["Accept"] = "application/json"
        return headers

    async def refresh_llms(self) -> list[LLM]:
        url = self._join_url(
            self.config.get(llm_api_base),
            self.codec.models_endpoint,
        )
        started = time.perf_counter()
        try:
            models = await self.codec.get_models(
                client=self.agent.http_client,
                url=url,
                headers=self._model_headers(),
                timeout=self._request_timeout,
            )
        except Exception:
            self.logger.exception("Model refresh failed endpoint=%s", self._safe_endpoint(url))
            raise
        self.logger.info("Models refreshed protocol=%s count=%d duration_ms=%.1f", self.config.get(llm_api_protocol), len(models), (time.perf_counter() - started) * 1000)
        return models

    async def get_model_info(self, model_name: str) -> LLM | None:
        encoded_name = quote(model_name, safe="/:@-._~")
        base = self.config.get(llm_api_base)
        for endpoint in self.codec.model_endpoints:
            url = self._join_url(
                base,
                endpoint.format(model_name=encoded_name),
            )
            info = await self.codec.get_model_info(
                client=self.agent.http_client,
                url=url,
                headers=self._model_headers(),
                timeout=self._request_timeout,
            )
            if info is not None:
                return info
        return None

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
    def _safe_endpoint(url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.netloc}{parsed.path}" or "<unknown>"

    @staticmethod
    def _resolve_model(ctx: BeforeLlmCallCtx) -> LLM:
        if ctx.run.llm is None:
            raise RuntimeError("No LLM selected for the current run")
        return ctx.run.llm

    def _resolve_api_base(self, ctx: BeforeLlmCallCtx) -> str:
        return ctx.api_base or self.config.get(llm_api_base)

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
        return ApiProtocol(self.config.get(llm_api_protocol))

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
        started = time.perf_counter()
        self.logger.debug("LLM request started model=%s protocol=%s stream=%s endpoint=%s", effective_model.model_name, protocol.value, actual_stream, self._safe_endpoint(url))

        if actual_stream:
            body = codec.enable_streaming(body)
            headers["Accept"] = "text/event-stream"
            try:
                async with self.agent.http_client.stream("POST", url, json=body, headers=headers, timeout=self._stream_timeout) as resp:
                    if resp.status_code >= 400:
                        err_body = (await resp.aread()).decode(errors="replace")
                        self.logger.error("LLM stream failed status=%d endpoint=%s", resp.status_code, self._safe_endpoint(url))
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
                    self.logger.info("LLM stream completed model=%s events=%d duration_ms=%.1f", effective_model.model_name, event_count, (time.perf_counter() - started) * 1000)
            except LLMResponseError:
                raise
            except HTTPError as exc:
                self.logger.error("LLM stream HTTP error endpoint=%s error_type=%s", self._safe_endpoint(url), type(exc).__name__, exc_info=exc)
                raise LLMResponseError(f"LLM HTTP stream failed: {exc}") from exc
            except Exception as exc:
                self.logger.error("Unexpected LLM stream error endpoint=%s error_type=%s", self._safe_endpoint(url), type(exc).__name__, exc_info=exc)
                raise
        else:
            try:
                response = await self.agent.http_client.post(url, json=body, headers=headers, timeout=self._request_timeout)
                response.raise_for_status()
                payload = response.json()
            except HTTPStatusError as exc:
                err_body = exc.response.text if exc.response else "no response"
                self.logger.error("LLM request failed status=%d endpoint=%s", exc.response.status_code, self._safe_endpoint(url))
                raise LLMResponseError(f"LLM HTTP request failed ({exc.response.status_code}): {err_body}") from exc
            except HTTPError as exc:
                self.logger.error("LLM request HTTP error endpoint=%s error_type=%s", self._safe_endpoint(url), type(exc).__name__, exc_info=exc)
                raise LLMResponseError(f"LLM HTTP request failed: {exc}") from exc
            except ValueError as exc:
                self.logger.error("LLM returned invalid JSON endpoint=%s", self._safe_endpoint(url), exc_info=exc)
                raise LLMResponseError("LLM returned invalid JSON") from exc

            llm_response = codec.parse_response(payload)
            for block in llm_response.content:
                yield block
            yield StreamEnd(
                stop_reason=llm_response.stop_reason,
                usage=llm_response.usage,
                meta=llm_response.meta,
            )
            self.logger.info("LLM request completed model=%s blocks=%d duration_ms=%.1f", effective_model.model_name, len(llm_response.content), (time.perf_counter() - started) * 1000)

    async def _iter_sse_events(self, response: httpx.Response) -> AsyncIterator[tuple[str | None, dict[str, Any]]]:
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
                        self.logger.warning("Failed to parse SSE JSON event")
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
                    self.logger.warning("Failed to parse trailing SSE JSON event")

    @property
    def _stream_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(connect=10.0, read=self.config.get(llm_stream_read_timeout), write=10.0, pool=10.0)

    @property
    def _request_timeout(self) -> float:
        return self.config.get(llm_request_timeout)

