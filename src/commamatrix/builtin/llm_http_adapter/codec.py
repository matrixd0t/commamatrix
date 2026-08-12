# builtin/llm_http_adapter/codec.py

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from enum import StrEnum
from json import loads
from typing import Any, ClassVar

from httpx2 import AsyncClient

from ...components.dialog import DialogItem, DialogItemType
from ...components.file_storage import DataType, FileContext, file_to_context, read_file
from ...components.hook import BeforeLlmCallCtx
from ...components.llm_adapter import (
    LLM,
    LLMResponse,
    LLMResponseBlock,
    structured_output_schema,
    StreamDelta,
    StreamEnd,
)


class ApiProtocol(StrEnum):
    """
    Three built-in API protocols
    """
    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES = "responses"
    ANTHROPIC_MESSAGES = "anthropic_messages"


def wire_meta(kind: str, value: Any, **extra: Any) -> dict[str, Any]:
    return {"llm": {"wire": {"kind": kind, "value": value, **extra}}}


class ApiCodec(ABC):
    protocol: ApiProtocol | str
    endpoint: str
    models_endpoint = "/v1/models"
    model_endpoints = (
        "/v1/models/{model_name}",
        "/v1/model/{model_name}",
        "/v1/models/{model_name}/endpoints",
    )
    can_stream: bool = False

    registry: ClassVar[dict[str, ApiCodec]] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None):
            cls.registry[cls.protocol] = cls()

    async def get_models(
        self,
        *,
        client: AsyncClient,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> list[LLM]:
        response = await client.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        raw_models = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(raw_models, list):
            raise ValueError("LLM models response must contain a data list")
        return [
            self.parse_model(model)
            for model in raw_models
            if isinstance(model, dict)
        ]

    async def get_model_info(
        self,
        *,
        client: AsyncClient,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> LLM | None:
        response = await client.get(url, headers=headers, timeout=timeout)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        model = payload.get("data", payload) if isinstance(payload, dict) else None
        if not isinstance(model, dict):
            raise ValueError("LLM model response must contain a model object")
        return self.parse_model(model)

    def parse_model(self, data: dict[str, Any]) -> LLM:
        model_name = data.get("id") or data.get("model_id")
        if not isinstance(model_name, str) or not model_name:
            raise ValueError("LLM model response does not contain an id")

        architecture = data.get("architecture")
        modalities: dict[str, set[DataType]] = {}
        if isinstance(architecture, dict):
            for field_name in ("input", "output"):
                source_name = f"{field_name}_modalities"
                if source_name in architecture:
                    modalities[field_name] = self._parse_modalities(
                        architecture[source_name]
                    )

        pricing = data.get("pricing")
        if not isinstance(pricing, dict):
            endpoints = data.get("endpoints")
            if isinstance(endpoints, list):
                pricing = next(
                    (
                        endpoint.get("pricing")
                        for endpoint in endpoints
                        if isinstance(endpoint, dict)
                        and isinstance(endpoint.get("pricing"), dict)
                    ),
                    {},
                )
        if not isinstance(pricing, dict):
            pricing = {}

        reasoning_modes = self._parse_reasoning_modes(data)
        return LLM(
            model_name=model_name,
            modalities=modalities,
            cost={
                "input_tokens": self._price_per_million(pricing.get("prompt")),
                "output_tokens": self._price_per_million(pricing.get("completion")),
                "cache_read_tokens": self._price_per_million(
                    pricing.get("input_cache_read", pricing.get("cache_read"))
                ),
                "cache_write_tokens": self._price_per_million(
                    pricing.get("input_cache_write", pricing.get("cache_write"))
                ),
            },
            reasoning_modes=reasoning_modes,
            meta=dict(data),
        )

    @classmethod
    def _parse_reasoning_modes(cls, data: dict[str, Any]) -> list[str]:
        value: Any = None
        for key in (
            "reasoning_modes",
            "supported_reasoning_modes",
            "reasoning_efforts",
            "supported_reasoning_efforts",
        ):
            if key in data:
                value = data[key]
                break
        if value is None and isinstance(data.get("reasoning_level"), dict):
            reasoning_data = data["reasoning_level"]
            value = reasoning_data.get("modes", reasoning_data.get("efforts"))
        if isinstance(value, str):
            value = (value,)
        if not isinstance(value, Iterable):
            return []

        modes = {mode for mode in value if isinstance(mode, str)}
        order = {"none": 0, "minimal": 1, "low": 2, "medium": 3, "high": 4, "xhigh": 5, "xxhigh": 6, "max": 7}
        return sorted(modes, key=lambda mode: (order.get(mode, len(order)), mode))

    @staticmethod
    def _parse_modalities(value: Any) -> set[DataType]:
        if isinstance(value, str):
            value = (value,)
        if not isinstance(value, Iterable):
            return set()
        result: set[DataType] = set()
        for item in value:
            try:
                result.add(DataType(item))
            except (TypeError, ValueError):
                continue
        return result

    @staticmethod
    def _price_per_million(value: Any) -> float:
        try:
            return float(value or 0) * 1_000_000
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _input_modalities(ctx: BeforeLlmCallCtx) -> set[DataType]:
        model = ctx.run.llm
        return model.modalities.input if isinstance(model, LLM) else set()

    async def _file_context(self, ctx: BeforeLlmCallCtx, item: DialogItem, *, modalities: Iterable[DataType | str] | DataType | str | None = None) -> FileContext | None:
        if item.item_type in {DialogItemType.IMAGE_INPUT, DialogItemType.IMAGE_OUTPUT}:
            content_type = DataType.IMAGE
            field_name = "image"
        elif item.item_type in {DialogItemType.FILE_INPUT, DialogItemType.FILE_OUTPUT}:
            content_type = DataType.FILE
            field_name = "file"
        else:
            return None

        try:
            item_data = loads(item.content)
        except (TypeError, ValueError):
            return None
        if not isinstance(item_data, dict):
            return None

        file_data = item_data.get(field_name, {})
        if not isinstance(file_data, dict):
            return None

        name = file_data.get("name")
        if not isinstance(name, str) or not name:
            name = None
        ext = file_data.get("ext")
        if not isinstance(ext, str):
            ext = None
        mime_type = file_data.get("mime_type")
        if not isinstance(mime_type, str) or not mime_type:
            mime_type = None

        external_url = file_data.get("url")
        if isinstance(external_url, str) and external_url:
            return FileContext(
                content=external_url,
                name=name or external_url,
                mime_type=mime_type or "application/octet-stream",
                data_type=content_type,
            )

        ref = file_data.get("ref")
        if not isinstance(ref, str) or not ref:
            return None

        resolved = await read_file(
            ref,
            file_storage=ctx.run.agent.file_storage.active,
            name=name,
            ext=ext,
            mime_type=mime_type,
            content_type=content_type,
            make_url=True,
        )
        if resolved is None:
            return None
        if modalities is None:
            modalities = self._input_modalities(ctx)
        return file_to_context(
            resolved,
            modalities=modalities,
            content_type=content_type,
        )

    @staticmethod
    def _model_name(model: LLM | str) -> str:
        return model if isinstance(model, str) else model.model_name

    @staticmethod
    def structured_output_format(ctx: BeforeLlmCallCtx) -> dict[str, Any] | None:
        if ctx.response_format is None:
            return None
        schema = structured_output_schema(ctx.response_format)
        return {
            "name": schema["name"],
            "strict": True,
            "schema": schema["schema"],
        }

    @abstractmethod
    async def build_request(self, *, model: LLM | str, ctx: BeforeLlmCallCtx) -> dict[str, Any]:
        ...

    @abstractmethod
    def parse_response(self, body: dict[str, Any]) -> LLMResponse:
        ...

    @staticmethod
    @abstractmethod
    def serialize_tools(ctx: BeforeLlmCallCtx) -> list[dict[str, Any]]:
        ...

    def enable_streaming(self, body: dict[str, Any]) -> dict[str, Any]:
        body["stream"] = True
        return body

    def parse_stream_event(
        self,
        event_type: str | None,
        data: dict[str, Any],
        acc: dict[str, Any],
    ) -> StreamDelta | LLMResponseBlock | None:
        raise NotImplementedError(f"{self.__class__.__name__} does not support streaming")

    def flush_stream(self, acc: dict[str, Any]) -> tuple[list[LLMResponseBlock], StreamEnd]:
        raise NotImplementedError(f"{self.__class__.__name__} does not support streaming")
