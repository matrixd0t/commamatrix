# builtin/llm_http_adapter/codec.py

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from ...components.dialog import DialogItem
from ...components.hook import BeforeLlmCallCtx
from ...components.llm_adapter import LLMResponse, LLMResponseBlock, StreamDelta, StreamEnd


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

    @abstractmethod
    async def build_request(self, *, model: str, ctx: BeforeLlmCallCtx) -> dict[str, Any]:
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
