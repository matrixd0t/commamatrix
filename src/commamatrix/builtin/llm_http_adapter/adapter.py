# builtin/llm_http_adapter/adapter.py

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from httpx import AsyncClient, HTTPError

from ...components.config import ConfigField
from ...components.hook import BeforeLlmCallCtx
from ...components.llm_adapter import LLMAdapter, LLMResponse, LLMResponseError
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

model = ConfigField[str](
    name="llm_model",
    description="Default model name",
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


class LLMHTTPAdapter(LLMAdapter):
    codec_registry = ApiCodec.registry

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)

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

    def _resolve_model(self, ctx: BeforeLlmCallCtx) -> str:
        return ctx.model or self.config.get(model)

    def _resolve_api_base(self, ctx: BeforeLlmCallCtx) -> str:
        return ctx.api_base or self.config.get(api_base)

    def _resolve_protocol(self, ctx: BeforeLlmCallCtx) -> ApiProtocol:
        if ctx.api_protocol:
            try:
                return ApiProtocol(ctx.api_protocol)
            except ValueError:
                pass
        return self._detect_protocol(self._resolve_model(ctx))

    @staticmethod
    def _detect_protocol(model_name: str) -> ApiProtocol:
        if model_name.startswith("claude-"):
            return ApiProtocol.ANTHROPIC_MESSAGES
        return ApiProtocol.CHAT_COMPLETIONS

    def _build_headers(self, protocol: ApiProtocol) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if protocol is ApiProtocol.ANTHROPIC_MESSAGES:
            headers["x-api-key"] = self.config.get(anthropic_api_key)
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {self.config.get(openai_api_key)}"
        return headers

    async def ask_llm(self, ctx: BeforeLlmCallCtx) -> LLMResponse:
        effective_model = self._resolve_model(ctx)
        effective_base = self._resolve_api_base(ctx)
        protocol = self._resolve_protocol(ctx)
        codec = self._resolve_codec(protocol)
        headers = self._build_headers(protocol)
        url = self._join_url(effective_base, codec.endpoint)
        body = await codec.build_request(model=effective_model, ctx=ctx)

        try:
            async with AsyncClient(headers=headers, timeout=120) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
                payload = response.json()
        except HTTPError as exc:
            body = exc.response.text if exc.response else "no response"
            raise LLMResponseError(f"LLM HTTP request failed ({exc.response.status_code}): {body}") from exc
        except ValueError as exc:
            raise LLMResponseError("LLM returned invalid JSON") from exc

        return codec.parse_response(payload)
