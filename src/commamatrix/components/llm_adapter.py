# components/llm_adapter.py

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING
from json import dumps

from ..core.utils import to_jsonable
from ..core.base.service import AbstractService
from ..core.base.manager import ServiceInstanceManager, ServiceInstanceRegistry
from .dialog import DialogItem, DialogItemType, DialogRole, DialogOrigin


if TYPE_CHECKING:
    from .hook import BeforeLlmCallCtx
    from ..core.agent import Agent

LLM_ADAPTER_ATTRIBUTE = "__commamatrix_llm_adapter__"


class LLMError(Exception):
    ...


class LLMResponseError(LLMError):
    ...


class LLMTruncatedError(LLMError):
    ...


@dataclass(slots=True, kw_only=True)
class ToolCall:
    """Data for a single tool invocation request from the LLM."""

    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any]

    def dump_json(self) -> str:
        return dumps(to_jsonable({'tool_call_id': self.tool_call_id, 'tool_name': self.tool_name, 'tool_args': self.tool_args}), ensure_ascii=False)


@dataclass(slots=True, kw_only=True)
class ToolCallResult:
    """Result of a tool call. Contains output content and an abort flag
    set by before_tool_call hooks."""

    tool_call_id: str
    content: Any
    abort: bool = False

    @classmethod
    def aborted(cls, tool_call_id: str, reason: str) -> ToolCallResult:
        return cls(tool_call_id=tool_call_id, abort=True, content=f'Tool call aborted: {reason}')

    def dump_json(self) -> str:
        return dumps({'tool_call_id': self.tool_call_id, 'content': to_jsonable(self.content)}, ensure_ascii=False)


class StopReason(StrEnum):
    """Why the LLM stopped generating: end of turn, tool use, max tokens, or error."""

    END_TURN = 'end_turn'
    TOOL_USE = 'tool_use'
    MAX_TOKENS = 'max_tokens'
    ERROR = 'error'


@dataclass(slots=True, kw_only=True)
class Usage:
    """Token and cost tracking for an LLM response."""

    usd: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class LLMResponseBlock(ABC):
    """Typed block within an LLM response. Subclasses represent text,
    images, files, and tool calls as a uniform sequence."""

    @abstractmethod
    def content_str(self) -> str: ...

    @abstractmethod
    def item_type(self) -> DialogItemType: ...

    def to_dialog_item(self, role: DialogRole, user: str, origin: DialogOrigin, previous_item_id: int | None = None) -> DialogItem:
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
    """Complete LLM response composed of typed content blocks
    with stop reason and usage statistics."""

    stop_reason: StopReason = StopReason.END_TURN
    content: list[LLMResponseBlock] = field(default_factory=list)
    usage: Usage | None = None
    model: str | None = None
    raw: Any = None
    meta: dict[str, Any] = field(default_factory=dict)


class LLMAdapter(AbstractService):
    """Abstract LLM provider. Subclasses implement ask_llm() to
    convert a BeforeLlmCallCtx into an LLMResponse by calling
    the actual provider API."""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None):
            setattr(cls, LLM_ADAPTER_ATTRIBUTE, True)

    @abstractmethod
    async def ask_llm(self, ctx: BeforeLlmCallCtx) -> LLMResponse:
        ...


class LLMAdapterManager(ServiceInstanceManager):
    """Manages LLM adapter instances using first-adapter pattern.
    The first discovered adapter is used for all LLM calls."""

    base_type = LLMAdapter
    marker_attribute = LLM_ADAPTER_ATTRIBUTE
    id_prefix = "llm_adapter"

    def __init__(self, agent: Agent, **kwargs: object) -> None:
        super().__init__(agent, **kwargs)

    @property
    def _active(self) -> LLMAdapter:
        instances = self.instances
        if instances:
            return instances[0]
        raise RuntimeError("No LLM adapters registered")

    async def ask_llm(self, ctx: Any) -> Any:
        return await self._active.ask_llm(ctx)
