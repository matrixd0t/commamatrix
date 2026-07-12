# core/hook_manager.py

from __future__ import annotations

from typing import Any

from .extension_manager import ExtensionManager
from ..api.hooks import HookDescriptor
from ..builtin.python.hook_source import PythonHookSource


class HookManager(ExtensionManager[HookDescriptor]):
    """
    Manager for hook descriptors.

    Groups descriptors by ``event`` and fires them in priority order
    via their source's ``invoke()`` method.
    """

    def __init__(self) -> None:
        super().__init__()
        self.mount(PythonHookSource())
        self._handlers: dict[str, list[HookDescriptor]] = {}

    async def fire(self, event: str, ctx: Any) -> None:
        """
        Execute all hooks registered for *event* in priority order.

        Each handler is dispatched through its source's ``invoke()``,
        which supports both sync and async implementations.
        """
        for descriptor in self._handlers.get(event, []):
            await self._source_of(descriptor).invoke(descriptor, ctx)

    def _rebuild(self) -> None:
        """Group all descriptors by event and sort by priority."""
        by_event: dict[str, list[HookDescriptor]] = {}
        for descriptor in self.descriptors:
            by_event.setdefault(descriptor.event, []).append(descriptor)
        for event in by_event:
            by_event[event].sort(key=lambda d: d.priority)
        self._handlers = by_event
