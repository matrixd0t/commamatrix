# api/hooks.py

from __future__ import annotations

from abc import abstractmethod
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
HOOK_MODULES: set[str] = set()


@dataclass(frozen=True, slots=True)
class Hook(Generic[CtxT]):
    """
    Typed decorator for hook handlers.

    Does NOT register handlers directly — only stamps the function with
    metadata (``HOOK_ATTRIBUTE``) and records its module in
    ``HOOK_MODULES``.  Actual registration happens when a
    ``PythonHookSource`` scans those modules.

    Usage::

        @before_run
        async def my_handler(ctx: BeforeRunCtx) -> None: ...

        @before_run(priority=10)
        async def my_handler(ctx: BeforeRunCtx) -> None: ...
    """

    _event: HookEventType
    _ctx_type: type[CtxT]

    def __call__(
        self, fn: Handler[CtxT] | None = None, /, priority: int = 0
    ) -> Handler[CtxT]:
        def decorator(f: Handler[CtxT]) -> Handler[CtxT]:
            setattr(
                f,
                HOOK_ATTRIBUTE,
                {
                    "event": self._event,
                    "priority": priority,
                },
            )
            HOOK_MODULES.add(f.__module__)
            return f

        if fn is not None:
            return decorator(fn)
        return decorator

    def __repr__(self) -> str:
        return f"Hook[{self._ctx_type.__name__}](event={self._event!r})"


@dataclass(frozen=True, slots=True)
class HookDescriptor(ExtensionDescriptor):
    """
    Declarative descriptor of a single hook registration.

    Unlike the old registry-based approach, this descriptor is completely
    source-agnostic — it only declares *when* to fire (``event``) and in
    what *order* (``priority``).  The owning source keeps the executable
    handler separately from the descriptor.

    Fields:
        event:  Event identifier (e.g. ``"before_llm_call"``).
        priority:  Execution order — lower runs first.
        metadata:  Source-specific data (e.g. the Python callable).
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


class HookSource(ExtensionSource[HookDescriptor]):
    """Abstract source of hook descriptors and their handlers."""

    @abstractmethod
    def scan(self) -> list[HookDescriptor]:
        raise NotImplementedError

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
    """
    Shared mutable state for a single agentic loop run.

    Created once per ``Agent.run()`` invocation and passed through all
    hooks in that run.  Hooks can read/write ``state`` to share data
    across lifecycle stages.  ``agent`` provides access to the full
    Agent, its ToolManager, Storage, hooks, etc.
    """

    agent: Agent
    connector: Connector | None = None
    origin: DialogOrigin
    user: str
    run_id: str = field(default_factory=lambda: uuid4().hex)
    iteration: int = 0
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class OnAgentStartCtx(BaseEventCtx):
    """Fired on ``Agent.start()``"""

    agent: Agent


@dataclass(slots=True, kw_only=True)
class OnParsedCtx(BaseEventCtx):
    """Fired after a connector parses an incoming raw event into dialog items."""

    agent: Agent
    connector: Connector
    raw: dict
    dialog_items: list[DialogItem]
    previous_external_id: str | None = None


@dataclass(slots=True, kw_only=True)
class BeforeRunCtx(BaseEventCtx):
    """Fired before the agentic loop starts. Set ``abort=True`` to skip the run."""

    run: RunCtx
    abort: bool = False


@dataclass(slots=True, kw_only=True)
class BeforeLlmCallCtx(BaseEventCtx):
    """Fired before each LLM call. Hooks can modify model, dialog, tools, or params."""

    run: RunCtx
    model: str | None = None
    dialog: list[DialogItem]
    tools: list[ToolDescriptor]
    llm_call_params: dict = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class AfterLlmCallCtx(BaseEventCtx):
    """Fired after the LLM returns a response. Hooks can inspect or modify the response."""

    run: RunCtx
    response: LLMResponse


@dataclass(slots=True, kw_only=True)
class BeforeToolCallCtx(BaseEventCtx):
    """Fired before a tool is executed. Set ``abort_tool_call=True`` to skip it."""

    run: RunCtx
    tool_call: ToolCall
    abort_tool_call: bool = False
    abort_reason: str = ""


@dataclass(slots=True, kw_only=True)
class AfterToolCallCtx(BaseEventCtx):
    """Fired after a tool call completes, with the result."""

    run: RunCtx
    tool_call: ToolCall
    result: ToolCallResult


@dataclass(slots=True, kw_only=True)
class BeforeSendCtx(BaseEventCtx):
    """Fired before a dialog item is sent to the user via the connector."""

    run: RunCtx
    dialog_item: DialogItem


@dataclass(slots=True, kw_only=True)
class OnErrorCtx(BaseEventCtx):
    """Fired when an exception occurs during the run. Set ``suppress=True`` to swallow it."""

    run: RunCtx
    error: Exception
    suppress: bool = False


@dataclass(slots=True, kw_only=True)
class AfterRunCtx(BaseEventCtx):
    """Fired after the run finishes (always, even on error — in ``finally``)."""

    run: RunCtx
    error: Exception | None = None


# Typed decorator instances for each event
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
