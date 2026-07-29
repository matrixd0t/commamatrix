# builtin/llm_http_adapter/codec.py

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from enum import StrEnum
from json import loads
from typing import Any

from ...components.dialog import DialogItem, DialogItemType
from ...components.file_storage import DataType, FileContext, file_to_context, read_file
from ...components.hook import BeforeLlmCallCtx
from ...components.llm_adapter import LLM, LLMResponse, LLMResponseBlock, StreamDelta, StreamEnd


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
    can_stream: bool = False

    registry: dict[str, ApiCodec] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None):
            cls.registry[cls.protocol] = cls()

    @staticmethod
    def _input_modalities(ctx: BeforeLlmCallCtx) -> set[DataType]:
        model = ctx.run.model
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
            file_storage=ctx.run.agent.file_storage,
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
