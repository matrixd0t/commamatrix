# core/service.py

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from ..api.config import Config
from ..api.service import Service, ServiceDescriptor
from ..api.connector import OnEvent
from .extension_manager import ExtensionManager
from ..builtin.python.service_source import PythonServiceSource


__all__ = ["ServiceRegistry", "ManagedServiceManager", "ServiceManager", "CustomServiceManager"]


# ---------------------------------------------------------------------------
# ServiceRegistry — typed lookup for active service instances
# ---------------------------------------------------------------------------

T = Any


class ServiceRegistry:
    """Typed container for active service instances by class or descriptor id."""

    def __init__(self) -> None:
        self._by_class: dict[type, object] = {}
        self._by_id: dict[str, object] = {}

    def __setitem__(self, key: type | str, value: object) -> None:
        if isinstance(key, str):
            self._by_id[key] = value
        else:
            self._by_class[key] = value

    def __getitem__(self, key: type[T]) -> T:
        return self._by_class[key]  # type: ignore[return-value]

    def get(self, key: type[T]) -> T | None:
        return self._by_class.get(key)  # type: ignore[return-value]

    def get_by_id(self, descriptor_id: str) -> object | None:
        return self._by_id.get(descriptor_id)

    def get_all(self, base: type[T]) -> list[T]:
        result: list[T] = []
        seen: set[int] = set()
        for inst in self._by_class.values():
            if isinstance(inst, base) and id(inst) not in seen:
                result.append(inst)
                seen.add(id(inst))
        for inst in self._by_id.values():
            if isinstance(inst, base) and id(inst) not in seen:
                result.append(inst)
                seen.add(id(inst))
        return result  # type: ignore[return-value]

    def require(self, key: type[T]) -> T:
        value = self._by_class.get(key)
        if value is None:
            raise KeyError(f"Service {key.__name__} not registered")
        return value  # type: ignore[return-value]

    def remove_by_instance(self, instance: object) -> None:
        for key, value in list(self._by_class.items()):
            if value is instance:
                del self._by_class[key]
                break
        for key, value in list(self._by_id.items()):
            if value is instance:
                del self._by_id[key]
                break

    def values(self) -> set[object]:
        return set(self._by_class.values()) | set(self._by_id.values())

    def clear(self) -> None:
        self._by_class.clear()
        self._by_id.clear()

    def __contains__(self, key: type | str) -> bool:
        if isinstance(key, str):
            return key in self._by_id
        return key in self._by_class


# ---------------------------------------------------------------------------
# ManagedServiceManager — unified instance lifecycle manager
# ---------------------------------------------------------------------------

class ManagedServiceManager(ExtensionManager[ServiceDescriptor]):
    """Base manager that reconciles Service instances with descriptors.

    Handles creation, fingerprint-based restart, stop, and registry
    integration for any discoverable Service subclass.
    """

    def __init__(self, python_source: Any) -> None:
        super().__init__()
        self._python_source = python_source
        self.mount(self._python_source)
        self._instances: dict[str, Service] = {}
        self._instance_fingerprints: dict[str, str] = {}
        self._start_order: list[str] = []
        self._registry: ServiceRegistry | None = None

    def set_scope(self, scope: list[str]) -> None:
        self._python_source.set_scope(scope)

    @property
    def instances(self) -> list[Service]:
        return [self._instances[sid] for sid in self._start_order if sid in self._instances]

    def get_by_id(self, descriptor_id: str) -> Service | None:
        return self._instances.get(descriptor_id)

    async def reconcile(self, config: Config, registry: ServiceRegistry) -> None:
        """Synchronize active instances with current descriptors."""
        self._registry = registry
        desired: dict[str, ServiceDescriptor] = {d.id: d for d in self.descriptors}

        for sid in list(self._instances):
            if sid not in desired:
                instance = self._instances.pop(sid)
                self._instance_fingerprints.pop(sid, None)
                self._start_order.remove(sid)
                await _call_stop(instance)
                registry.remove_by_instance(instance)

        for sid, descriptor in desired.items():
            old_fp = self._instance_fingerprints.get(sid)
            new_fp = descriptor.fingerprint
            if old_fp is not None and old_fp != new_fp:
                instance = self._instances.pop(sid)
                self._start_order.remove(sid)
                await _call_stop(instance)
                registry.remove_by_instance(instance)

        for sid, descriptor in desired.items():
            if sid in self._instances:
                continue
            instance = descriptor.service_cls(config=config)
            await _call_start(instance)
            self._instances[sid] = instance
            self._instance_fingerprints[sid] = descriptor.fingerprint
            self._start_order.append(sid)
            registry[sid] = instance
            registry[descriptor.service_cls] = instance

    async def stop_all_instances(self) -> None:
        for sid in reversed(self._start_order):
            instance = self._instances.get(sid)
            if instance is not None:
                await _call_stop(instance)
        self._instances.clear()
        self._instance_fingerprints.clear()
        self._start_order.clear()

    async def refresh_instances(self) -> None:
        await asyncio.gather(*(_call_refresh(inst) for inst in self._instances.values()))


# ---------------------------------------------------------------------------
# CustomServiceManager — discovers and manages custom Service subclasses
# ---------------------------------------------------------------------------

class CustomServiceManager(ManagedServiceManager):
    """Discover and manage custom Service subclasses.

    Provider slots (Storage, FileStorage, LLMAdapter) are filtered out
    since they are managed by dedicated provider managers.
    """

    def __init__(self) -> None:
        source = PythonServiceSource()
        super().__init__(source)


# ---------------------------------------------------------------------------
# ServiceManager — root lifecycle composite for all agent-owned services
# ---------------------------------------------------------------------------

class ServiceManager:
    """Root lifecycle composite owning all agent-owned services.

    Manages tool, hook, connector, and provider managers as well as
    custom service instances. Provides a single start / refresh / stop
    entry point for the Agent. NOT a Service itself.
    """

    def __init__(self, config: Config, on_event: OnEvent | None = None) -> None:
        from .tool_manager import ToolManager
        from .hook_manager import HookManager
        from .connector_manager import ConnectorManager
        from .llm_adapter_manager import LLMAdapterManager
        from .storage_manager import StorageManager
        from .file_storage_manager import FileStorageManager

        self._config = config
        self._registry = ServiceRegistry()
        self._started = False
        self._refresh_lock = asyncio.Lock()
        self._dirty = False

        self.tool_manager = ToolManager()
        self.hook_manager = HookManager()
        self.llm_adapter_manager = LLMAdapterManager()
        self.storage_manager = StorageManager()
        self.file_storage_manager = FileStorageManager()
        self.custom_service_manager = CustomServiceManager()
        self.connector_manager = ConnectorManager(on_event=on_event, config=config)

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
            child.on_change = self._mark_dirty

    @property
    def registry(self) -> ServiceRegistry:
        return self._registry

    def _mark_dirty(self) -> None:
        self._dirty = True

    def set_scope(self, scope: list[str]) -> None:
        scope_key = tuple(scope)
        if scope_key != self._last_scope:
            self._last_scope = scope_key
            for child in self._children:
                child.set_scope(scope)
            self._dirty = True

    async def start(self) -> None:
        """Start all child managers, discover extensions, and create instances.

        If any step fails, previously started resources are cleaned up.
        """
        if self._started:
            return
        started_children: list[Any] = []
        try:
            for child in self._children:
                await _call_start_async(child)
                started_children.append(child)
            for child in self._children:
                child.scan()
            await self.connector_manager.flush_pending_stops()
            await self._reconcile_providers()
            await self._refresh_all_instances()
            self._started = True
            self._dirty = False
            await self.connector_manager.start_listeners()
        except BaseException:
            # Stop all created service instances before stopping managers
            for mgr in (self.custom_service_manager, self.llm_adapter_manager,
                        self.storage_manager, self.file_storage_manager):
                try:
                    await mgr.stop_all_instances()
                except Exception:
                    pass
            self._registry.clear()
            for child in reversed(started_children):
                try:
                    await _call_stop_async(child)
                except Exception:
                    pass
            raise

    async def refresh(self, force: bool = False) -> None:
        """Re-scan and reconcile all children if force or something changed."""
        async with self._refresh_lock:
            if not force and not self._dirty:
                return
            self._dirty = False
            for child in self._children:
                child.scan()
            await self.connector_manager.flush_pending_stops()
            await self._reconcile_providers()
            await self._refresh_all_instances()

    async def stop(self) -> None:
        if not self._started:
            return
        await self.connector_manager.stop_listeners()
        await self.custom_service_manager.stop_all_instances()
        await asyncio.gather(
            self.llm_adapter_manager.stop_all_instances(),
            self.storage_manager.stop_all_instances(),
            self.file_storage_manager.stop_all_instances(),
        )
        for child in reversed(self._children):
            await _call_stop_async(child)
        self._registry.clear()
        self._started = False

    async def _reconcile_providers(self) -> None:
        await self.llm_adapter_manager.reconcile(self._config, self._registry)
        await self.storage_manager.reconcile(self._config, self._registry)
        await self.file_storage_manager.reconcile(self._config, self._registry)
        await self.custom_service_manager.reconcile(self._config, self._registry)

    async def _refresh_all_instances(self) -> None:
        await self.llm_adapter_manager.refresh_instances()
        await self.storage_manager.refresh_instances()
        await self.file_storage_manager.refresh_instances()
        for inst in self.custom_service_manager.instances:
            await _call_refresh(inst)


async def _call_start(service: Any) -> None:
    result = service.start()
    if inspect.isawaitable(result):
        await result


async def _call_stop(service: Any) -> None:
    result = service.stop()
    if inspect.isawaitable(result):
        await result


async def _call_refresh(service: Any) -> None:
    result = service.refresh()
    if inspect.isawaitable(result):
        await result


async def _call_start_async(child: Any) -> None:
    result = child.start()
    if inspect.isawaitable(result):
        await result


async def _call_stop_async(child: Any) -> None:
    result = child.stop()
    if inspect.isawaitable(result):
        await result
