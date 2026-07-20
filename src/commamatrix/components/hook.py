# components/hook.py

from __future__ import annotations

import asyncio
import inspect
import weakref
from abc import abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast
from collections.abc import Awaitable, Callable

from ..core.classes.descriptor import Descriptor
from ..core.classes.source import Source, PythonSource
from ..core.classes.manager import Manager
from ..core.classes.ordering import normalize_constraint_refs, ConstraintRef

if TYPE_CHECKING:
    from ..core.agent import Agent
    from .connector import Connector
    from .dialog import DialogItem, DialogOrigin
    from .llm_adapter import LLMResponse, ToolCallResult, ToolCall
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
    origin: DialogOrigin
    user: str
    run_id: str = field(default_factory=lambda: uuid4().hex)
    iteration: int = 0
    state: dict[str, Any] = field(default_factory=dict)
    tool_output_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    """Serialises ``send + persist`` of tool-call results.

    This lock ensures that tool-result ``DialogItem`` items are stored
    one at a time and their ``previous_item_id`` chain is kept
    consistent.  It does NOT impose any ordering on parallel
    nested tool results — each result carries its own
    ``tool_call_id`` that links it back to the originating call.
    """

    tool_output_tail: int | None = None


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


class HookSource(Source[HookDescriptor]):
    """Source ABC for hook invocation. Each source owns the handler
    callables it discovered and must implement invoke()."""

    @abstractmethod
    async def invoke(self, descriptor: HookDescriptor, ctx: object) -> object:
        raise NotImplementedError


class PythonHookSource(PythonSource[HookDescriptor], HookSource):
    """Scopes to modules with @Hook-decorated functions. Maintains an
    internal handler map for direct invocation by descriptor ID."""

    def __init__(self) -> None:
        super().__init__()
        self._handlers: dict[str, Any] = {}

    def scan(self) -> list[HookDescriptor]:
        self._handlers.clear()
        return super().scan()

    @property
    def marker_attribute(self) -> str:
        return HOOK_ATTRIBUTE

    def build_descriptor(self, object_name: str, obj: object) -> HookDescriptor | None:
        params = getattr(obj, HOOK_ATTRIBUTE)
        descriptor_id = f"hook://{obj.__module__}/{object_name}"
        self._handlers[descriptor_id] = cast(Any, obj)
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
        result = handler(ctx)
        if inspect.isawaitable(result):
            return await result
        return result


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
on_parsed = Hook[OnParsedCtx](HookEventType.ON_PARSED, OnParsedCtx)
before_run = Hook[BeforeRunCtx](HookEventType.BEFORE_RUN, BeforeRunCtx)
before_llm_call = Hook[BeforeLlmCallCtx](HookEventType.BEFORE_LLM_CALL, BeforeLlmCallCtx)
after_llm_call = Hook[AfterLlmCallCtx](HookEventType.AFTER_LLM_CALL, AfterLlmCallCtx)
before_tool_call = Hook[BeforeToolCallCtx](HookEventType.BEFORE_TOOL_CALL, BeforeToolCallCtx)
after_tool_call = Hook[AfterToolCallCtx](HookEventType.AFTER_TOOL_CALL, AfterToolCallCtx)
before_send = Hook[BeforeSendCtx](HookEventType.BEFORE_SEND, BeforeSendCtx)
on_error = Hook[OnErrorCtx](HookEventType.ON_ERROR, OnErrorCtx)
after_run = Hook[AfterRunCtx](HookEventType.AFTER_RUN, AfterRunCtx)
