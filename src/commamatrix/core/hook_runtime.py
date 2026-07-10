# core/hook_runtime.py

from __future__ import annotations

from typing import Any

from .extension_runtime import ExtensionRuntime
from ..api.hooks import HookDescriptor


class HookRuntime(ExtensionRuntime[HookDescriptor]):
    """
    Runtime for hook descriptors.

    Groups descriptors by ``event`` and fires them in priority order
    via their source's ``invoke()`` method.
    """

    def __init__(self) -> None:
        super().__init__()
        self._handlers: dict[str, list[HookDescriptor]] = {}

    async def fire(self, event: str, ctx: Any) -> None:
        """
        Execute all hooks registered for *event* in priority order.

        Each handler is dispatched through its source's ``invoke()``,
        which supports both sync and async implementations.
        """
        for descriptor in self._handlers.get(event, []):
            await descriptor.source.invoke(descriptor, ctx)

    def _rebuild(self) -> None:
        """Group all descriptors by event and sort by priority."""
        by_event: dict[str, list[HookDescriptor]] = {}
        for descriptor in self.descriptors:
            by_event.setdefault(descriptor.event, []).append(descriptor)
        for event in by_event:
            by_event[event].sort(key=lambda d: d.priority)
        self._handlers = by_event
