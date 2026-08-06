# components/llm_adapter.py

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from dataclasses import dataclass, field
from json import dumps
from collections.abc import AsyncIterator, Iterator
from typing import Any, TYPE_CHECKING

from ..utils import to_jsonable
from ..core.classes.lifecycle_registry import lifecycle_component
from ..core.classes.service import AbstractService
from ..core.classes.manager import ServiceInstanceManager
from ..core.classes.source import PythonServiceSource
from .config import ConfigField
from .dialog import DialogItem, DialogItemType, DialogRole, DialogOrigin
from .file_storage import DataType

if TYPE_CHECKING:
    from .hook import BeforeLlmCallCtx
    from ..core.agent import Agent

LLM_ADAPTER_ATTRIBUTE = "__commamatrix_llm_adapter__"

reasoning = ConfigField[str](
    name="reasoning",
    default="",
    description="Default reasoning mode (if applicable to the model). Values 'max' / 'highest' / 'lowest' are universal",
)


class LLMError(Exception):
    ...


class LLMResponseError(LLMError):
    ...


class LLMTruncatedError(LLMError):
    ...


def _normalize_modalities(value: Any) -> set[DataType]:
    if value is None:
        return set()
    if isinstance(value, (DataType, str)):
        value = (value,)
    return {
        modality if isinstance(modality, DataType) else DataType(modality)
        for modality in value
    }


@dataclass(slots=True, kw_only=True)
class LLMModalities:
    input: set[DataType] = field(default_factory=lambda: {DataType.TEXT})
    output: set[DataType] = field(default_factory=lambda: {DataType.TEXT})

    def __post_init__(self) -> None:
        self.input = _normalize_modalities(self.input)
        self.output = _normalize_modalities(self.output)


@dataclass(slots=True, kw_only=True)
class Cost:
    """Prices in US dollars per one million tokens."""
    input_tokens: float = 0.0
    output_tokens: float = 0.0
    cache_read_tokens: float = 0.0
    cache_write_tokens: float = 0.0


@dataclass(slots=True, kw_only=True)
class LLM:
    model_name: str
    modalities: LLMModalities | dict[str, Any] = field(default_factory=LLMModalities)
    cost: Cost | dict[str, Any] = field(default_factory=Cost)
    reasoning_modes: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.modalities, dict):
            self.modalities = LLMModalities(**self.modalities)
        if isinstance(self.cost, dict):
            self.cost = Cost(**self.cost)


@dataclass(slots=True, kw_only=True)
class ToolCall:
    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any]

    def dump_json(self) -> str:
        return dumps(to_jsonable({"tool_call_id": self.tool_call_id, "tool_name": self.tool_name, "tool_args": self.tool_args}), ensure_ascii=False)


@dataclass(slots=True, kw_only=True)
class ToolCallResult:
    tool_call_id: str
    content: Any
    abort: bool = False

    @classmethod
    def aborted(cls, tool_call_id: str, reason: str) -> ToolCallResult:
        return cls(tool_call_id=tool_call_id, abort=True, content=f"Tool call aborted: {reason}")

    def dump_json(self) -> str:
        return dumps({"tool_call_id": self.tool_call_id, "content": to_jsonable(self.content)}, ensure_ascii=False)


class StopReason(StrEnum):
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    LENGTH = "length"
    ERROR = "error"


@dataclass(slots=True, kw_only=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass(slots=True, kw_only=True)
class LLMResponseBlock(ABC):
    meta: dict[str, Any] = field(default_factory=dict)

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
            meta=dict(self.meta),
        )


@dataclass(slots=True, kw_only=True)
class LLMResponseTextBlock(LLMResponseBlock):
    content: str

    def content_str(self) -> str:
        return self.content

    def item_type(self) -> DialogItemType:
        return DialogItemType.OUTPUT


@dataclass(slots=True, kw_only=True)
class LLMResponseImageBlock(LLMResponseBlock):
    ref: str
    ext: str
    content: bytes | None = None

    def content_str(self) -> str:
        return dumps({"image": {"ref": self.ref, "ext": self.ext}}, ensure_ascii=False)

    def item_type(self) -> DialogItemType:
        return DialogItemType.IMAGE_OUTPUT


@dataclass(slots=True, kw_only=True)
class LLMResponseFileBlock(LLMResponseBlock):
    ref: str
    ext: str
    content: bytes | None = None

    def content_str(self) -> str:
        return dumps({"file": {"ref": self.ref, "ext": self.ext}}, ensure_ascii=False)

    def item_type(self) -> DialogItemType:
        return DialogItemType.FILE_OUTPUT


@dataclass(slots=True, kw_only=True)
class LLMResponseReasoningBlock(LLMResponseBlock):
    content: str

    def content_str(self) -> str:
        return self.content

    def item_type(self) -> DialogItemType:
        return DialogItemType.REASONING


@dataclass(slots=True, kw_only=True)
class LLMResponseToolCallBlock(LLMResponseBlock):
    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any]

    def content_str(self) -> str:
        return dumps({"tool_call_id": self.tool_call_id, "tool_name": self.tool_name, "tool_args": self.tool_args}, ensure_ascii=False)

    def item_type(self) -> DialogItemType:
        return DialogItemType.TOOL_CALL


@dataclass(slots=True, kw_only=True)
class StreamDelta:
    content: str
    delta_type: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class StreamEnd:
    stop_reason: StopReason = StopReason.END_TURN
    usage: Usage | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class LLMResponse:
    """Complete LLM response composed of typed content blocks
    with stop reason and usage statistics."""

    stop_reason: StopReason = StopReason.END_TURN
    content: list[LLMResponseBlock] = field(default_factory=list)
    usage: Usage | None = None
    raw: Any = None
    meta: dict[str, Any] = field(default_factory=dict)


class LLMAdapter(AbstractService):
    """
    Abstract LLM adapter.
    Subclasses provide their models and implement ask_llm() as an async
    generator yielding StreamDelta, LLMResponseBlock, and StreamEnd events.
    """

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None):
            setattr(cls, LLM_ADAPTER_ATTRIBUTE, True)

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        self.llms: list[LLM] = []

    async def start(self) -> None:
        self.llms = await self.refresh_llms()
        self.logger.info("LLM adapter started adapter=%s models=%d", type(self).__name__, len(self.llms))

    @abstractmethod
    async def refresh_llms(self) -> list[LLM]:
        """Return models with adapter-provided, ascending reasoning_modes."""

    def resolve_reasoning_mode(self, llm: LLM) -> str | None:
        """Resolve the configured reasoning mode for a model."""
        modes = llm.reasoning_modes
        if len(modes) <= 1:
            return None

        configured = self.config.get(reasoning)
        if configured in modes:
            return configured
        if configured in {"max", "highest"}:
            return modes[-1]
        if configured == "lowest":
            return modes[0]
        return None

    def ask_llm(self, ctx: BeforeLlmCallCtx, *, stream: bool = False) -> AsyncIterator[StreamDelta | LLMResponseBlock | StreamEnd]:
        raise NotImplementedError


class PythonLLMAdapterSource(PythonServiceSource):
    def __init__(self) -> None:
        super().__init__(base_type=LLMAdapter, marker_attribute=LLM_ADAPTER_ATTRIBUTE, id_prefix="llm_adapter")


@lifecycle_component(key="llm_adapter", priority=700, after="instruction_manager")
class LLMAdapterManager(ServiceInstanceManager[LLMAdapter]):
    """Manage adapters and resolve models to their owning adapter."""

    base_type = LLMAdapter
    marker_attribute = LLM_ADAPTER_ATTRIBUTE
    id_prefix = "llm_adapter"

    def __init__(self, agent: Agent, **kwargs: object) -> None:
        super().__init__(agent, source=PythonLLMAdapterSource(), **kwargs)

    def iter_llms(self) -> Iterator[tuple[LLMAdapter, LLM]]:
        for adapter in self.instances:
            yield from ((adapter, llm) for llm in adapter.llms)

    def resolve_adapter(self, llm: LLM) -> LLMAdapter | None:
        identity_matches = [
            adapter
            for adapter, candidate in self.iter_llms()
            if candidate is llm
        ]
        if identity_matches:
            return identity_matches[0]

        name_matches = [
            adapter
            for adapter, candidate in self.iter_llms()
            if candidate.model_name == llm.model_name
        ]
        if name_matches:
            return name_matches[0]
        return None

    def ask_llm(self, ctx: BeforeLlmCallCtx, *, stream: bool = False) -> AsyncIterator[StreamDelta | LLMResponseBlock | StreamEnd]:
        adapter = ctx.run.adapter
        if adapter is None:
            raise RuntimeError("No LLM adapter selected for the current run")
        return adapter.ask_llm(ctx, stream=stream)
