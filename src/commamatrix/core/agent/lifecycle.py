# core/agent/lifecycle.py

from __future__ import annotations

import asyncio
from typing import Any

from ...components.config import Config
from ...components.connector import OnEvent
from ...components.tool import ToolManager
from ...components.hook import HookManager
from ...components.connector import ConnectorManager
from ...components.llm_adapter import LLMAdapterManager
from ...components.storage import StorageManager
from ...components.file_storage import FileStorageManager
from ..base.manager import ServiceInstanceRegistry, CustomInstanceServiceManager
from ..utils import await_if_needed


class AgentLifecycle:
    """Root lifecycle composite owning all agent-owned services.

    Manages tool, hook, connector, and provider managers as well as
    custom service instances. Provides a single start / refresh / stop
    entry point for the Agent. NOT a AbstractService itself.
    """

    def __init__(self, config: Config, on_event: OnEvent | None = None) -> None:
        self._config = config
        self._registry = ServiceInstanceRegistry()
        self._refresh_lock = asyncio.Lock()
        self._started = False
        self._changed = False

        self.tool_manager = ToolManager()
        self.hook_manager = HookManager()
        self.llm_adapter_manager = LLMAdapterManager(config=config, registry=self._registry)
        self.storage_manager = StorageManager(config=config, registry=self._registry)
        self.file_storage_manager = FileStorageManager(config=config, registry=self._registry)
        self.custom_service_manager = CustomInstanceServiceManager(config=config, registry=self._registry)
        self.connector_manager = ConnectorManager(config=config, registry=self._registry, on_event=on_event)

        self._children: list[Any] = [
            self.tool_manager,
            self.hook_manager,
            self.llm_adapter_manager,
            self.storage_manager,
            self.file_storage_manager,
            self.custom_service_manager,
            self.connector_manager,
        ]

        self._last_scope: tuple[str, ...] = ()

        for child in self._children:
            child.on_change = self._mark_changed

    @property
    def registry(self) -> ServiceInstanceRegistry:
        return self._registry

    def _mark_changed(self) -> None:
        self._changed = True

    def set_scope(self, scope: list[str]) -> None:
        scope_key = tuple(scope)
        if scope_key != self._last_scope:
            self._last_scope = scope_key
            for child in self._children:
                child.set_scope(scope)
            self._mark_changed()

    async def start(self) -> None:
        """Start all child managers, discover extensions, and create instances.

        If any step fails, previously started resources are cleaned up.
        """
        if self._started:
            return
        started_children: list[Any] = []
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
        """Re-scan and reconcile all children if force or something changed."""
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
