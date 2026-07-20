# builtin/llm_http_adapter/codec.py

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from ...components.dialog import DialogItem
from ...components.hook import BeforeLlmCallCtx
from ...components.llm_adapter import LLMResponse


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

    registry: dict[str, ApiCodec | str] = {}

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
