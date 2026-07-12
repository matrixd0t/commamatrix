# api/llm_adapter.py

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING
from json import dumps

from .dialog import DialogItem, DialogItemType, DialogRole, DialogOrigin

if TYPE_CHECKING:
    from .config import Config
    from .hooks import BeforeLlmCallCtx


class LLMError(Exception):
    ...


class LLMResponseError(LLMError):
    ...


class LLMTruncatedError(LLMError):
    ...


@dataclass(slots=True, kw_only=True)
class ToolCall:
    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any]

    def dump_json(self) -> str:
        return dumps({'tool_call_id': self.tool_call_id, 'tool_name': self.tool_name, 'tool_args': self.tool_args}, ensure_ascii=False)


@dataclass(slots=True, kw_only=True)
class ToolCallResult:
    tool_call_id: str
    content: str
    abort: bool = False

    @classmethod
    def aborted(cls, tool_call_id: str, reason: str) -> ToolCallResult:
        return cls(tool_call_id=tool_call_id, abort=True, content=f'Tool call aborted: {reason}')

    def dump_json(self) -> str:
        return dumps({'tool_call_id': self.tool_call_id, 'content': self.content}, ensure_ascii=False)


class StopReason(StrEnum):
    END_TURN = 'end_turn'
    TOOL_USE = 'tool_use'
    MAX_TOKENS = 'max_tokens'
    ERROR = 'error'


@dataclass(slots=True, kw_only=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class LLMResponseBlock(ABC):
    @abstractmethod
    def content_str(self) -> str: ...

    @abstractmethod
    def item_type(self) -> DialogItemType: ...

    def to_dialog_item(
        self,
        role: DialogRole,
        user: str,
        origin: DialogOrigin,
        previous_item_id: int | None = None,
    ) -> DialogItem:
        return DialogItem(
            content=self.content_str(),
            item_type=self.item_type(),
            role=role,
            user=user,
            origin=origin,
            previous_item_id=previous_item_id,
        )


@dataclass(slots=True, kw_only=True)
class LLMResponseTextBlock(LLMResponseBlock):
    text: str

    def content_str(self) -> str:
        return self.text

    def item_type(self) -> DialogItemType:
        return DialogItemType.OUTPUT


@dataclass(slots=True, kw_only=True)
class LLMResponseImageBlock(LLMResponseBlock):
    ref: str
    ext: str
    content: bytes | None = None

    def content_str(self) -> str:
        return dumps({'image': {'ref': self.ref, 'ext': self.ext}}, ensure_ascii=False)

    def item_type(self) -> DialogItemType:
        return DialogItemType.IMAGE_OUTPUT


@dataclass(slots=True, kw_only=True)
class LLMResponseFileBlock(LLMResponseBlock):
    ref: str
    ext: str
    content: bytes | None = None

    def content_str(self) -> str:
        return dumps({'file': {'ref': self.ref, 'ext': self.ext}}, ensure_ascii=False)

    def item_type(self) -> DialogItemType:
        return DialogItemType.FILE_OUTPUT


@dataclass(slots=True, kw_only=True)
class LLMResponseToolCallBlock(LLMResponseBlock):
    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any]

    def content_str(self) -> str:
        return dumps({'tool_call_id': self.tool_call_id, 'tool_name': self.tool_name, 'tool_args': self.tool_args}, ensure_ascii=False)

    def item_type(self) -> DialogItemType:
        return DialogItemType.TOOL_CALL


@dataclass(slots=True, kw_only=True)
class LLMResponse:
    stop_reason: StopReason
    content: list[LLMResponseBlock] = field(default_factory=list)
    usage: Usage | None = None
    model: str | None = None
    raw: Any = None
    meta: dict[str, Any] = field(default_factory=dict)


class LLMAdapter(ABC):
    def __init__(self, config: Config) -> None:
        """Initialize from per-agent Config. Subclasses read their fields via config.get(field)."""

    @abstractmethod
    async def ask_llm(self, ctx: BeforeLlmCallCtx) -> LLMResponse:
        ...
