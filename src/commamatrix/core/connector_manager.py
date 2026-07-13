# core/connector_manager.py

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from .extension_manager import ExtensionManager
from ..api.connector import Connector, ConnectorDescriptor, OnEvent
from ..api.config import Config
from ..builtin.python.connector_source import PythonConnectorSource


class ConnectorManager(ExtensionManager[ConnectorDescriptor]):
    """Manager for connector descriptors with listener ownership.

    Owns connector instances and their listener tasks.
    Reconciliation creates new connectors, stops removed ones (awaiting
    their tasks), and restarts changed ones. When already started,
    new connectors automatically begin listening.

    Reconciliation is two-phase:
    1. _reconcile_connectors() (sync) — called from scan(), identifies
       removed/changed connectors and stashes them in _pending_stop.
    2. flush_pending_stops() (async) — awaited by ServiceManager after
       scan, actually stops old listeners before new ones start.
    """

    def __init__(self, on_event: OnEvent | None = None, config: Config | None = None) -> None:
        super().__init__()
        self.config = config
        self._python_source = PythonConnectorSource()
        self.mount(self._python_source)
        self._active: dict[str, Connector] = {}
        self._active_fingerprints: dict[str, str] = {}
        self._on_event = on_event
        self._started = False
        self._pending_stop: list[Connector] = []

    def set_scope(self, scope: list[str]) -> None:
        self._python_source.set_scope(scope)

    def bind(self, on_event: OnEvent) -> None:
        self._on_event = on_event

    async def start(self) -> None:
        await super().start()
        self._started = True

    async def stop(self) -> None:
        await self.stop_listeners()
        self._started = False
        await super().stop()

    async def stop_listeners(self) -> None:
        await asyncio.gather(
            *(c.stop_listening() for c in self._active.values()),
            return_exceptions=True,
        )

    async def flush_pending_stops(self) -> None:
        """Await cleanup of connectors removed during the last scan."""
        pending = self._pending_stop
        self._pending_stop = []
        if pending:
            await asyncio.gather(
                *(c.stop_listening() for c in pending),
                return_exceptions=True,
            )

    def scan(self) -> bool:
        changed = super().scan()
        if changed:
            self._reconcile_connectors()
        return changed

    def _reconcile_connectors(self) -> None:
        """Synchronize connector instances with current descriptors.

        Removed/changed connectors are stashed in _pending_stop for
        async cleanup by flush_pending_stops().
        """
        desired: dict[str, ConnectorDescriptor] = {d.id: d for d in self.descriptors}

        for old_id in list(self._active):
            if old_id not in desired:
                connector = self._active.pop(old_id)
                self._active_fingerprints.pop(old_id, None)
                self._pending_stop.append(connector)

        for desc_id, descriptor in desired.items():
            old_fp = self._active_fingerprints.get(desc_id)
            new_fp = descriptor.fingerprint
            if old_fp is not None and old_fp != new_fp:
                connector = self._active.pop(desc_id)
                self._active_fingerprints.pop(desc_id)
                self._pending_stop.append(connector)

        for desc_id, descriptor in desired.items():
            if desc_id in self._active:
                continue
            connector = descriptor.connector_cls(config=self.config)
            self._active[desc_id] = connector
            self._active_fingerprints[desc_id] = descriptor.fingerprint
            if self._started and self._on_event is not None:
                connector.start_listening(self._on_event)

    def resolve(self, config: Config) -> list[Connector]:
        """Return all active connector instances."""
        return list(self._active.values())

    async def start_listeners(self) -> list[asyncio.Task]:
        """Start listener tasks for all connectors that don't have one."""
        if self._on_event is None:
            return []
        tasks: list[asyncio.Task] = []
        for connector in self._active.values():
            task = connector.listener_task
            if task is None or task.done():
                task = connector.start_listening(self._on_event)
                tasks.append(task)
        return tasks
