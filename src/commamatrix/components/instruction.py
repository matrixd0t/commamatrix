# components/instruction.py

from __future__ import annotations

import weakref
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, cast

from ..core.classes.descriptor import Descriptor
from ..core.classes.lifecycle_registry import lifecycle_component
from ..core.classes.manager import Manager
from ..core.classes.ordering import ConstraintRef, normalize_constraint_refs
from ..core.classes.source import PythonSource
from ..utils import await_if_needed
from .dialog import DialogItem, DialogItemType, DialogRole
from .file_storage import DataType
from .hook import BeforeLlmCallCtx, RunCtx, before_llm_call

INSTRUCTION_ATTRIBUTE = "__commamatrix_instruction__"


@dataclass(slots=True, kw_only=True)
class InstructionCtx:
    """Context passed to instruction handlers."""
    run: RunCtx


type InstructionHandler = Callable[[InstructionCtx], str | None]


@dataclass(frozen=True, slots=True)
class Instruction:
    """Decorator factory that stamps INSTRUCTION_ATTRIBUTE on handler functions."""

    def __call__(
        self,
        fn: InstructionHandler | None = None,
        /,
        priority: int = 0,
        before: ConstraintRef | Iterable[ConstraintRef] | None = None,
        after: ConstraintRef | Iterable[ConstraintRef] | None = None,
    ) -> InstructionHandler:
        before_norm = normalize_constraint_refs(before)
        after_norm = normalize_constraint_refs(after)

        def decorator(f: InstructionHandler) -> InstructionHandler:
            setattr(
                f,
                INSTRUCTION_ATTRIBUTE,
                {
                    "priority": priority,
                    "before": before_norm,
                    "after": after_norm,
                },
            )
            return f

        if fn is not None:
            return decorator(fn)
        return decorator


@dataclass(frozen=True, slots=True)
class InstructionDescriptor(Descriptor):
    """Metadata for a registered instruction: name, module, priority,
    and before/after ordering constraints."""

    name: str
    module: str
    priority: int = 0
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "module": self.module,
            "priority": self.priority,
            "before": self.before,
            "after": self.after,
            "meta": self.meta,
        }


class PythonInstructionSource(PythonSource[InstructionDescriptor]):
    """Scopes to modules with @instruction-decorated functions."""

    def __init__(self) -> None:
        super().__init__()
        self._handlers: dict[str, InstructionHandler] = {}

    def scan(self) -> list[InstructionDescriptor]:
        self._handlers.clear()
        return super().scan()

    @property
    def marker_attribute(self) -> str:
        return INSTRUCTION_ATTRIBUTE

    def build_descriptor(self, object_name: str, obj: object) -> InstructionDescriptor | None:
        params = getattr(obj, INSTRUCTION_ATTRIBUTE)
        descriptor_id = f"instruction://{obj.__module__}/{object_name}"
        self._handlers[descriptor_id] = cast(InstructionHandler, obj)
        return InstructionDescriptor(
            id=descriptor_id,
            name=object_name,
            module=obj.__module__ or "",
            priority=params.get("priority", 0),
            before=params.get("before", ()),
            after=params.get("after", ()),
            meta={},
            _source_ref=weakref.ref(self),
        )

    async def invoke(self, descriptor: InstructionDescriptor, ctx: InstructionCtx) -> str | None:
        handler = self._handlers.get(descriptor.id)
        if handler is None:
            raise RuntimeError(f"Instruction {descriptor.id} is not owned by this source")
        return await await_if_needed(handler(ctx))


@lifecycle_component(key="instruction_manager", priority=800, after="hook_manager")
class InstructionManager(Manager[InstructionDescriptor]):
    """Manages instruction descriptors with before/after ordering."""

    def __init__(self, agent, **kwargs) -> None:
        super().__init__(agent, **kwargs)
        self._ordered: list[InstructionDescriptor] = []
        self._python_source = PythonInstructionSource()
        self.mount(self._python_source)

    def set_scope(self, scope: list[str]) -> None:
        self._python_source.set_scope(scope)

    async def collect(self, run: RunCtx) -> list[str]:
        """Invoke all instructions in order, collect non-None outputs."""
        ctx = InstructionCtx(run=run)
        parts: list[str] = []
        for descriptor in self._ordered:
            output = await self._source_of(descriptor).invoke(descriptor, ctx)
            if output is not None:
                parts.append(output)
        return parts

    def _rebuild(self) -> None:
        from ..core.classes.ordering import resolve_order

        self._ordered = resolve_order(
            self.descriptors,
            aliases=lambda d: (d.name, f"{d.module}.{d.name}" if d.module else d.name),
            priority=lambda d: d.priority,
            before=lambda d: d.before,
            after=lambda d: d.after,
        )


instruction = Instruction()
"""Decorator for registering instruction functions that generate system prompt fragments.

The decorated function must accept a single ``InstructionCtx`` argument and return
``str | None``.  Return a string to include it in the system prompt, ``None`` to skip.

The function may be sync or async.

Signature::

    def my_instruction(ctx: InstructionCtx) -> str | None: ...

Args for the decorator (all optional):
    priority: int = 0           — higher runs first
    before: ConstraintRef       — must execute before the named instruction
    after: ConstraintRef        — must execute after the named instruction

Examples::

    @instruction
    def current_date(ctx: InstructionCtx) -> str:
        return f"Today: {datetime.now():%Y-%m-%d}"

    @instruction(priority=10)
    def system_info(ctx: InstructionCtx) -> str:
        return "You are a helpful assistant."

    @instruction(before="system_info")
    def user_tz(ctx: InstructionCtx) -> str | None:
        tz = ctx.run.state.get("timezone")
        return f"User timezone: {tz}" if tz else None

    @instruction(after=current_date)
    async def dynamic_rules(ctx: InstructionCtx) -> str:
        rules = await fetch_rules(ctx.run.user)
        return "\\n".join(rules)
"""


@instruction(priority=-500)
def connector_modalities(ctx: InstructionCtx) -> str | None:
    """Describe attachment markers supported by the current connector."""
    connector = ctx.run.agent.connector_manager.resolve_for_origin(ctx.run.origin)

    attachment_modalities = tuple(
        modality
        for modality in DataType
        if modality is not DataType.TEXT and modality in connector.modalities.output
    )
    if not attachment_modalities:
        return None

    markers = ", ".join(f"[{modality.value}:file_id_or_path]" for modality in attachment_modalities)
    return (
        "# Attachments\n"
        "To attach content from local storage to your response, write a marker "
        f"using one of these forms: {markers}. Use a file ID or a path as the value."
    )


@before_llm_call
async def add_instructions(ctx: BeforeLlmCallCtx) -> None:
    """Collect instruction outputs and prepend as system message."""
    if not ctx.run.aggregate_instructions:
        return
    instruction_manager: InstructionManager = ctx.run.agent.instruction_manager
    parts = await instruction_manager.collect(ctx.run)
    if not parts:
        return
    system_item = DialogItem(
        content="\n\n".join([p.strip(' \n') for p in parts]),
        item_type=DialogItemType.INPUT,
        role=DialogRole.SYSTEM,
        origin=ctx.run.origin,
    )
    ctx.dialog.insert(0, system_item)
