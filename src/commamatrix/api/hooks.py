# api/hooks.py

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4
from typing import TYPE_CHECKING, Any, Generic, TypeVar
from collections.abc import Awaitable, Callable

from .connector import Connector
from .dialog import DialogItem, DialogOrigin
from ..extensions import ExtensionDescriptor, ExtensionSource
from .llm_adapter import LLMResponse, ToolCallResult, ToolCall
from .tool import ToolDescriptor

if TYPE_CHECKING:
    from ..core.agent import Agent

CtxT = TypeVar("CtxT")

type Handler[CtxT] = Callable[[CtxT], object | Awaitable[object]]

HOOK_ATTRIBUTE = "__commamatrix_hook__"


@dataclass(frozen=True, slots=True)
class Hook(Generic[CtxT]):
    """Typed decorator for hook handlers.

    Stamps the function with metadata. Actual registration happens when
    a PythonHookSource scans scoped modules.
    """

    _event: HookEventType
    _ctx_type: type[CtxT]

    def __call__(self, fn: Handler[CtxT] | None = None, /, priority: int = 0) -> Handler[CtxT]:
        def decorator(f: Handler[CtxT]) -> Handler[CtxT]:
            setattr(
                f,
                HOOK_ATTRIBUTE,
                {
                    "event": self._event,
                    "priority": priority,
                },
            )
            return f

        if fn is not None:
            return decorator(fn)
        return decorator

    def __repr__(self) -> str:
        return f"Hook[{self._ctx_type.__name__}](event={self._event!r})"


@dataclass(frozen=True, slots=True)
class HookDescriptor(ExtensionDescriptor):
    """Declarative descriptor of a single hook registration.

    Source-agnostic — declares when to fire (event) and in
    what order (priority). The owning source keeps the executable
    handler separately from the descriptor.
    """

    event: str
    priority: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event": self.event,
            "priority": self.priority,
            "metadata": self.metadata,
        }


class HookSource(ExtensionSource[HookDescriptor], ABC):
    """Abstract source of hook descriptors and their handlers."""

    @abstractmethod
    async def invoke(self, descriptor: HookDescriptor, ctx: object) -> object:
        raise NotImplementedError


class HookEventType(StrEnum):
    """Well-known hook event identifiers used by the agent loop."""

    ON_AGENT_START = "on_agent_start"
    ON_PARSED = "on_parsed"
    BEFORE_RUN = "before_run"
    BEFORE_LLM_CALL = "before_llm_call"
    AFTER_LLM_CALL = "after_llm_call"
    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"
    BEFORE_SEND = "before_send"
    ON_ERROR = "on_error"
    AFTER_RUN = "after_run"


@dataclass(slots=True, kw_only=True)
class BaseEventCtx:
    """Base class for all hook event contexts."""

    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class RunCtx:
    """Shared mutable state for a single agentic loop run."""

    agent: Agent
    connector: Connector | None = None
    origin: DialogOrigin
    user: str
    run_id: str = field(default_factory=lambda: uuid4().hex)
    iteration: int = 0
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class OnAgentStartCtx(BaseEventCtx):
    agent: Agent


@dataclass(slots=True, kw_only=True)
class OnParsedCtx(BaseEventCtx):
    agent: Agent
    connector: Connector
    raw: dict
    dialog_items: list[DialogItem]
    previous_external_id: str | None = None


@dataclass(slots=True, kw_only=True)
class BeforeRunCtx(BaseEventCtx):
    run: RunCtx
    abort: bool = False


@dataclass(slots=True, kw_only=True)
class BeforeLlmCallCtx(BaseEventCtx):
    run: RunCtx
    model: str | None = None
    dialog: list[DialogItem]
    tools: list[ToolDescriptor]
    llm_call_params: dict = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class AfterLlmCallCtx(BaseEventCtx):
    run: RunCtx
    response: LLMResponse


@dataclass(slots=True, kw_only=True)
class BeforeToolCallCtx(BaseEventCtx):
    run: RunCtx
    tool_call: ToolCall
    abort_tool_call: bool = False
    abort_reason: str = ""


@dataclass(slots=True, kw_only=True)
class AfterToolCallCtx(BaseEventCtx):
    run: RunCtx
    tool_call: ToolCall
    result: ToolCallResult


@dataclass(slots=True, kw_only=True)
class BeforeSendCtx(BaseEventCtx):
    run: RunCtx
    dialog_item: DialogItem


@dataclass(slots=True, kw_only=True)
class OnErrorCtx(BaseEventCtx):
    run: RunCtx
    error: Exception
    suppress: bool = False


@dataclass(slots=True, kw_only=True)
class AfterRunCtx(BaseEventCtx):
    run: RunCtx
    error: Exception | None = None


on_agent_start = Hook(HookEventType.ON_AGENT_START, OnAgentStartCtx)
on_parsed = Hook(HookEventType.ON_PARSED, OnParsedCtx)
before_run = Hook(HookEventType.BEFORE_RUN, BeforeRunCtx)
before_llm_call = Hook(HookEventType.BEFORE_LLM_CALL, BeforeLlmCallCtx)
after_llm_call = Hook(HookEventType.AFTER_LLM_CALL, AfterLlmCallCtx)
before_tool_call = Hook(HookEventType.BEFORE_TOOL_CALL, BeforeToolCallCtx)
after_tool_call = Hook(HookEventType.AFTER_TOOL_CALL, AfterToolCallCtx)
before_send = Hook(HookEventType.BEFORE_SEND, BeforeSendCtx)
on_error = Hook(HookEventType.ON_ERROR, OnErrorCtx)
after_run = Hook(HookEventType.AFTER_RUN, AfterRunCtx)
