# components/hook.py

from __future__ import annotations

import asyncio
import inspect
import weakref
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast
from collections.abc import Awaitable, Callable

from ..core.classes.descriptor import Descriptor
from ..core.classes.source import PythonSource
from ..core.classes.manager import Manager
from ..core.classes.ordering import normalize_constraint_refs, ConstraintRef
from ..utils import await_if_needed

if TYPE_CHECKING:
    from ..core.agent import Agent
    from .connector import Connector
    from .dialog import DialogItem, DialogOrigin
    from .llm_adapter import LLM, LLMAdapter, LLMResponse, ToolCallResult, ToolCall
    from .tool import ToolDescriptor

CtxT = TypeVar("CtxT")

type Handler[CtxT] = Callable[[CtxT], object | Awaitable[object]]

HOOK_ATTRIBUTE = "__commamatrix_hook__"


class HookEventType(StrEnum):
    """All ten lifecycle events in order of occurrence during a run."""

    ON_AGENT_START = "on_agent_start"
    ON_PARSED = "on_parsed"
    BEFORE_RUN = "before_run"
    BEFORE_LLM_CALL = "before_llm_call"
    AFTER_LLM_CALL = "after_llm_call"
    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"
    BEFORE_SEND = "before_send"
    AFTER_SEND = "after_send"
    ON_ERROR = "on_error"
    AFTER_RUN = "after_run"


@dataclass(slots=True, kw_only=True)
class BaseEventCtx:
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class RunCtx:
    """Per-run context injected into every hook. Carries agent, connector,
    origin, user identity, iteration count, and mutable state dict."""

    agent: Agent
    connector: Connector | None = None
    adapter: LLMAdapter | None = None
    origin: DialogOrigin
    user: str
    llm: LLM | None = None
    run_id: str = field(default_factory=lambda: uuid4().hex)
    iteration: int = 0
    state: dict[str, Any] = field(default_factory=dict)
    chain_state: dict[str, Any] = field(default_factory=dict)
    """Persistent state that carries across messages in the conversation chain.

    Unlike ``state`` (per-run only), ``chain_state`` is serialised into every 
    ``DialogItem.meta["chain"]`` and restored from the last item of the conversation branch when a new run starts.  
    This lets hooks and tools make cross-message decisions.
    """
    tool_output_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    """Serialises ``send + persist`` of tool-call results.
    
    This lock ensures that tool-result ``DialogItem`` items are stored one at a time and their ``previous_item_id`` chain is kept consistent.  
    It does NOT impose any ordering on parallel nested tool results — each result carries its own ``tool_call_id`` that links it back to the originating call.
    """
    tool_output_tail: int | None = None
    pending_input_items: list[DialogItem] = field(default_factory=list)
    last_item_id: int | None = None


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
    api_base: str | None = None
    api_protocol: str | None = None
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
    follow_up_items: list[DialogItem] = field(default_factory=list)
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
class AfterSendCtx(BaseEventCtx):
    run: RunCtx
    dialog_item: DialogItem
    external_id: str | None = None


@dataclass(slots=True, kw_only=True)
class OnErrorCtx(BaseEventCtx):
    run: RunCtx
    error: Exception
    suppress: bool = False


@dataclass(slots=True, kw_only=True)
class AfterRunCtx(BaseEventCtx):
    run: RunCtx
    error: Exception | None = None


@dataclass(frozen=True, slots=True)
class Hook(Generic[CtxT]):
    """Decorator factory that stamps HOOK_ATTRIBUTE on handler functions.
    Binds an event type to a context type for type-safe registration."""

    _event: HookEventType
    _ctx_type: type[CtxT]

    def __call__(
        self,
        fn: Handler[CtxT] | None = None,
        /,
        priority: int = 0,
        before: ConstraintRef | Iterable[ConstraintRef] | None = None,
        after: ConstraintRef | Iterable[ConstraintRef] | None = None,
    ) -> Handler[CtxT]:
        before_norm = normalize_constraint_refs(before)
        after_norm = normalize_constraint_refs(after)

        def decorator(f: Handler[CtxT]) -> Handler[CtxT]:
            setattr(
                f,
                HOOK_ATTRIBUTE,
                {
                    "event": self._event,
                    "priority": priority,
                    "before": before_norm,
                    "after": after_norm,
                },
            )
            return f

        if fn is not None:
            return decorator(fn)
        return decorator

    def __repr__(self) -> str:
        return f"Hook[{self._ctx_type.__name__}](event={self._event!r})"


@dataclass(frozen=True, slots=True)
class HookDescriptor(Descriptor):
    """Metadata for a registered hook handler: event, priority, name, module,
    and before/after ordering constraints. Priority determines execution order
    among unconstrained items; before/after take precedence over priority."""

    event: str
    priority: int
    name: str
    module: str
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event": self.event,
            "priority": self.priority,
            "name": self.name,
            "module": self.module,
            "before": self.before,
            "after": self.after,
            "meta": self.meta,
        }


class PythonHookSource(PythonSource[HookDescriptor]):
    """Scopes to modules with @Hook-decorated functions. Maintains an
    internal handler map for direct invocation by descriptor ID."""

    def __init__(self) -> None:
        super().__init__()
        self._handlers: dict[str, Handler[object]] = {}

    def scan(self) -> list[HookDescriptor]:
        self._handlers.clear()
        return super().scan()

    @property
    def marker_attribute(self) -> str:
        return HOOK_ATTRIBUTE

    def build_descriptor(self, object_name: str, obj: object) -> HookDescriptor | None:
        params = getattr(obj, HOOK_ATTRIBUTE)
        descriptor_id = f"hook://{obj.__module__}/{object_name}"
        self._handlers[descriptor_id] = cast(Handler[object], obj)
        return HookDescriptor(
            id=descriptor_id,
            event=params["event"].value,
            priority=params.get("priority", 0),
            name=object_name,
            module=obj.__module__ or "",
            before=params.get("before", ()),
            after=params.get("after", ()),
            meta={},
            _source_ref=weakref.ref(self),
        )

    async def invoke(self, descriptor: HookDescriptor, ctx: object) -> object:
        handler = self._handlers.get(descriptor.id)
        if handler is None:
            raise RuntimeError(f"Hook {descriptor.id} is not owned by this source")
        return await await_if_needed(handler(ctx))


class HookManager(Manager[HookDescriptor]):
    """Dispatches hook events respecting before/after constraints,
    falling back to priority (higher first) for unconstrained items."""

    def __init__(self, agent, **kwargs) -> None:
        super().__init__(agent, **kwargs)
        self._python_source = PythonHookSource()
        self.mount(self._python_source)
        self._handlers: dict[str, list[HookDescriptor]] = {}

    def set_scope(self, scope: list[str]) -> None:
        self._python_source.set_scope(scope)

    async def fire(self, event: str, ctx: Any) -> None:
        for descriptor in self._handlers.get(event, []):
            await self._source_of(descriptor).invoke(descriptor, ctx)

    def _rebuild(self) -> None:
        from ..core.classes.ordering import resolve_order

        by_event: dict[str, list[HookDescriptor]] = {}
        for descriptor in self.descriptors:
            by_event.setdefault(descriptor.event, []).append(descriptor)
        for event, group in by_event.items():
            by_event[event] = resolve_order(
                group,
                aliases=lambda d: (d.name, f"{d.module}.{d.name}" if d.module else d.name),
                priority=lambda d: d.priority,
                before=lambda d: d.before,
                after=lambda d: d.after,
            )
        self._handlers = by_event


on_agent_start = Hook[OnAgentStartCtx](HookEventType.ON_AGENT_START, OnAgentStartCtx)
"""Fired once when the agent starts (after lifecycle init).

The decorated function must accept ``OnAgentStartCtx`` and return ``None``.

Example::

    @on_agent_start
    async def log_start(ctx: OnAgentStartCtx) -> None:
        print(f"Agent {ctx.agent} started")
"""

on_parsed = Hook[OnParsedCtx](HookEventType.ON_PARSED, OnParsedCtx)
"""Fired after a connector parses an incoming event.

The decorated function must accept ``OnParsedCtx`` and return ``None``.

Example::

    @on_parsed(priority=5)
    async def log_message(ctx: OnParsedCtx) -> None:
        for item in ctx.dialog_items:
            print(f"[{item.origin}] {item.content}")
"""

before_run = Hook[BeforeRunCtx](HookEventType.BEFORE_RUN, BeforeRunCtx)
"""Fired before a run starts. Set ``ctx.abort = True`` to cancel the run.

The decorated function must accept ``BeforeRunCtx`` and return ``None``.

Example::

    @before_run
    async def check_rate_limit(ctx: BeforeRunCtx) -> None:
        if await is_rate_limited(ctx.run.user):
            ctx.abort = True

    @before_run(after=check_rate_limit)
    async def log_run(ctx: BeforeRunCtx) -> None:
        logger.info("Run %s started for %s", ctx.run.run_id, ctx.run.user)
"""

before_llm_call = Hook[BeforeLlmCallCtx](HookEventType.BEFORE_LLM_CALL, BeforeLlmCallCtx)
"""Fired before the LLM is called.  Mutate ``ctx.dialog``, ``ctx.run.adapter``, ``ctx.run.llm``,
``ctx.api_base``, ``ctx.tools``, or ``ctx.llm_call_params`` to influence the call.

The decorated function must accept ``BeforeLlmCallCtx`` and return ``None``.

Example::

    @before_llm_call
    async def override_model(ctx: BeforeLlmCallCtx) -> None:
        if ctx.run.state.get("use_fast_model"):
            ctx.run.llm = LLM(model_name="gpt-4o-mini")

    @before_llm_call(after=override_model)
    async def add_model_specific_instructions(ctx: BeforeLlmCallCtx) -> None:
        ...
"""

after_llm_call = Hook[AfterLlmCallCtx](HookEventType.AFTER_LLM_CALL, AfterLlmCallCtx)
"""Fired after the LLM responds.  Inspect or mutate ``ctx.response``.

The decorated function must accept ``AfterLlmCallCtx`` and return ``None``.

Signature::

    def my_hook(ctx: AfterLlmCallCtx) -> None: ...

Example::

    @after_llm_call
    async def log_tokens(ctx: AfterLlmCallCtx) -> None:
        usage = ctx.response.usage
        if usage:
            print(f"Tokens: {usage.input_tokens} in / {usage.output_tokens} out")
"""

before_tool_call = Hook[BeforeToolCallCtx](HookEventType.BEFORE_TOOL_CALL, BeforeToolCallCtx)
"""Fired before a tool is invoked.  Set ``ctx.abort_tool_call = True`` to skip
the call; mutate ``ctx.tool_call`` to change arguments.

The decorated function must accept ``BeforeToolCallCtx`` and return ``None``.

Example::

    @before_tool_call
    async def guard_dangerous_tools(ctx: BeforeToolCallCtx) -> None:
        if ctx.tool_call.tool_name == "run_sql" and "DROP" in str(ctx.tool_call.tool_args):
            ctx.abort_tool_call = True
            ctx.abort_reason = "DROP statements are not allowed"
"""

after_tool_call = Hook[AfterToolCallCtx](HookEventType.AFTER_TOOL_CALL, AfterToolCallCtx)
"""Fired after a tool returns its result.  Mutate ``ctx.result`` to alter
what the LLM sees.

The decorated function must accept ``AfterToolCallCtx`` and return ``None``.

Example::

    @after_tool_call
    async def truncate_long_results(ctx: AfterToolCallCtx) -> None:
        if len(ctx.result.content) > 10_000:
            ctx.result.content = ctx.result.content[:10_000] + "\\n... (truncated)"
"""

before_send = Hook[BeforeSendCtx](HookEventType.BEFORE_SEND, BeforeSendCtx)
"""Fired before a dialog item is sent to the connector and persisted.

The decorated function must accept ``BeforeSendCtx`` and return ``None``.

Example::

    @before_send
    async def censor_output(ctx: BeforeSendCtx) -> None:
        ctx.dialog_item.content = ctx.dialog_item.content.replace("SECRET", "***")
"""

after_send = Hook[AfterSendCtx](HookEventType.AFTER_SEND, AfterSendCtx)
"""Fired after a dialog item is persisted and delivered or delivery is skipped."""


on_error = Hook[OnErrorCtx](HookEventType.ON_ERROR, OnErrorCtx)
"""Fired when an exception occurs during a run.  Set ``ctx.suppress = True``
to prevent the error from being re-raised.

The decorated function must accept ``OnErrorCtx`` and return ``None``.

Example::

    @on_error
    async def log_error(ctx: OnErrorCtx) -> None:
        logger.exception("Run %s failed: %s", ctx.run.run_id, ctx.error)

    @on_error(after=log_error)
    async def suppress_timeout(ctx: OnErrorCtx) -> None:
        if isinstance(ctx.error, TimeoutError):
            ctx.suppress = True
"""

after_run = Hook[AfterRunCtx](HookEventType.AFTER_RUN, AfterRunCtx)
"""Fired after a run completes (success or failure).  ``ctx.error`` is
``None`` on success, the exception on failure.

The decorated function must accept ``AfterRunCtx`` and return ``None``.

Example::

    @after_run
    async def cleanup(ctx: AfterRunCtx) -> None:
        ctx.run.state.clear()
"""
