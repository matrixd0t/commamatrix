# core/agent/lifecycle.py

"""Root lifecycle composite for Agent-owned services.

AgentLifecycle takes a ready-made ordered list of agent-owned services from
Agent, wires manager on_change callbacks, and provides start/stop/refresh
entry points with transactional rollback support.
"""

from __future__ import annotations

import asyncio

from ..classes.manager import Manager, ServiceInstanceRegistry
from ..classes.service import AbstractService
from commamatrix.utils import await_if_needed


class AgentLifecycle:
    """Root lifecycle composite. Receives an ordered children list from Agent.

    Order: tool → hook → llm_adapter → storage → file_storage → service → connector → http_server.
    Supports transactional startup with rollback on failure.
    """

    def __init__(self, children: list[AbstractService], registry: ServiceInstanceRegistry) -> None:
        self._children = children
        self._registry = registry
        self._refresh_lock = asyncio.Lock()
        self._started = False
        self._changed = False
        self._last_scope: tuple[str, ...] = ()
        for child in children:
            if isinstance(child, Manager):
                child.on_change = self._mark_changed

    @property
    def registry(self) -> ServiceInstanceRegistry:
        return self._registry

    def get_manager(self, cls: type[Manager]) -> Manager | None:
        for mgr in self._children:
            if isinstance(mgr, cls):
                return mgr
        return None

    def set_scope(self, scope: list[str]) -> None:
        scope_key = tuple(scope)
        if scope_key != self._last_scope:
            self._last_scope = scope_key
            for child in self._children:
                if isinstance(child, Manager):
                    child.set_scope(scope)
            self._mark_changed()

    async def start(self) -> None:
        if self._started:
            return
        started_children: list[AbstractService] = []
        try:
            for child in self._children:
                started_children.append(child)
                await await_if_needed(child.start())
            self._started = True
            self._changed = False
        except BaseException:
            for child in reversed(started_children):
                try:
                    await await_if_needed(child.stop())
                except Exception:
                    pass
            self._registry.clear()
            raise

    async def refresh(self, force: bool = False) -> None:
        async with self._refresh_lock:
            if not force and not self._changed:
                return
            for child in self._children:
                await await_if_needed(child.refresh())
            self._changed = False

    async def stop(self) -> None:
        if not self._started:
            return
        for child in reversed(self._children):
            await await_if_needed(child.stop())
        self._registry.clear()
        self._started = False

    def _mark_changed(self) -> None:
        self._changed = True
