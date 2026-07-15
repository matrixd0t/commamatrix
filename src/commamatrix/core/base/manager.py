# core/base/manager.py

from __future__ import annotations

import asyncio
import hashlib
import weakref
from collections.abc import Callable, ValuesView
from typing import Any, Generic, TypeVar

from .descriptor import Descriptor, StaleDescriptorError
from .service import AbstractService, ServiceDescriptor
from .source import (
    Source,
    PythonProviderSource,
    PythonServiceSource,
    UnavailableSourceError
)
from ..utils import await_if_needed
from ...components.config import Config, ConfigField


D = TypeVar("D", bound=Descriptor)


class Manager(AbstractService, Generic[D]):
    on_change: Callable[[], None] | None

    def __init__(self) -> None:
        super().__init__()
        self._sources: list[Source[D]] = []
        self._descriptors: dict[str, D] = {}
        self._source_descriptor_ids: dict[int, set[str]] = {}
        self._source_invalidators: dict[int, Callable[[], None]] = {}
        self._fingerprint: str | None = None
        self.on_change = None

    @property
    def descriptors(self) -> ValuesView[D]:
        return self._descriptors.values()

    def _source_of(self, descriptor: D) -> Source[D]:
        self._ensure_current(descriptor)
        return descriptor._source_ref()

    def _ensure_current(self, descriptor: D) -> None:
        current = self._descriptors.get(descriptor.id)
        if current is not descriptor:
            raise StaleDescriptorError(f"Extension descriptor is no longer active: {descriptor.id}")

        source = descriptor._source_ref()
        if source is None or not source.available:
            raise UnavailableSourceError(f"Extension source is unavailable: {descriptor.id}")

    def is_current(self, descriptor: D) -> bool:
        try:
            self._ensure_current(descriptor)
        except (UnavailableSourceError, StaleDescriptorError):
            return False
        return True

    def mount(self, source: Source[D]) -> None:
        if source in self._sources:
            return

        manager_ref = weakref.ref(self)
        source_ref = weakref.ref(source)

        def invalidate() -> None:
            manager = manager_ref()
            mounted_source = source_ref()
            if manager is not None and mounted_source is not None:
                manager.invalidate(mounted_source)

        self._sources.append(source)
        self._source_invalidators[id(source)] = invalidate
        source._attach_invalidator(invalidate)

    def unmount(self, source: Source[D]) -> None:
        self.invalidate(source)
        invalidator = self._source_invalidators.pop(id(source), None)
        if invalidator is not None:
            source._detach_invalidator(invalidator)
        self._sources.remove(source)
        self._source_descriptor_ids.pop(id(source), None)

    async def start(self) -> None:
        for source in self._sources:
            source.restore()
            await await_if_needed(source.start())
        await self.refresh()

    async def stop(self) -> None:
        for source in reversed(self._sources):
            source.invalidate()
            await await_if_needed(source.stop())

    async def refresh(self) -> None:
        self.scan()

    def invalidate(self, source: Source[D]) -> bool:
        if source not in self._sources:
            return False

        descriptor_ids = self._source_descriptor_ids.get(id(source), set())
        removed = False
        for descriptor_id in descriptor_ids:
            if descriptor_id in self._descriptors:
                del self._descriptors[descriptor_id]
                removed = True

        if not removed:
            return False

        self._source_descriptor_ids[id(source)] = set()
        self._fingerprint = self._calculate_fingerprint()
        self._rebuild()
        self._notify_change()
        return True

    def scan(self) -> bool:
        descriptors: dict[str, D] = {}
        source_descriptor_ids: dict[int, set[str]] = {}

        for source in self._sources:
            if not source.available:
                source_descriptor_ids[id(source)] = set()
                continue
            current_ids: set[str] = set()
            for descriptor in source.scan():
                if descriptor.id in descriptors:
                    raise ValueError(f"Duplicate extension descriptor id: {descriptor.id}")
                descriptors[descriptor.id] = descriptor
                current_ids.add(descriptor.id)
            source_descriptor_ids[id(source)] = current_ids

        fingerprint = self._calculate_fingerprint(descriptors)
        if fingerprint == self._fingerprint:
            self._source_descriptor_ids = source_descriptor_ids
            return False

        self._descriptors = descriptors
        self._source_descriptor_ids = source_descriptor_ids
        self._fingerprint = fingerprint
        self._rebuild()
        self._notify_change()
        return True

    def _notify_change(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def _calculate_fingerprint(self, descriptors: dict[str, D] | None = None) -> str:
        current = self._descriptors if descriptors is None else descriptors
        fp = hashlib.sha256()
        for descriptor in sorted(current.values(), key=lambda item: item.id):
            fp.update(descriptor.fingerprint.encode())
        return fp.hexdigest()

    def _rebuild(self) -> None:
        """Rebuild specialized indexes after descriptors change."""


S = TypeVar("S", bound=AbstractService)


class InstanceManager(Manager[D], Generic[D, S]):
    def __init__(self, python_source: Source[D]) -> None:
        super().__init__()
        self._python_source = python_source
        self.mount(self._python_source)
        self._instances: dict[str, S] = {}
        self._instance_fingerprints: dict[str, str] = {}
        self._start_order: list[str] = []

    def set_scope(self, scope: list[str]) -> None:
        self._python_source.set_scope(scope)

    @property
    def instances(self) -> list[S]:
        return [self._instances[sid] for sid in self._start_order if sid in self._instances]

    def get_by_id(self, descriptor_id: str) -> S | None:
        return self._instances.get(descriptor_id)

    async def start(self) -> None:
        await super().start()
        await self.refresh()

    async def refresh(self) -> None:
        await super().refresh()
        await self._reconcile_instances()
        await self._refresh_instances()

    async def stop(self) -> None:
        await self._stop_all_instances()
        await super().stop()

    async def _reconcile_instances(self) -> None:
        desired: dict[str, D] = {d.id: d for d in self.descriptors}

        for sid in list(self._instances):
            if sid not in desired:
                instance = self._instances.pop(sid)
                self._instance_fingerprints.pop(sid, None)
                self._start_order.remove(sid)
                await self._stop_instance(instance)
                self._on_instance_removed(instance)

        for sid, descriptor in desired.items():
            old_fp = self._instance_fingerprints.get(sid)
            new_fp = descriptor.fingerprint
            if old_fp is not None and old_fp != new_fp:
                instance = self._instances.pop(sid)
                self._instance_fingerprints.pop(sid, None)
                self._start_order.remove(sid)
                await self._stop_instance(instance)
                self._on_instance_removed(instance)

        for sid, descriptor in desired.items():
            if sid in self._instances:
                continue
            instance = self._create_instance(descriptor)
            await self._start_instance(instance)
            self._instances[sid] = instance
            self._instance_fingerprints[sid] = descriptor.fingerprint
            self._start_order.append(sid)
            self._on_instance_added(instance, sid, descriptor)

    async def _stop_all_instances(self) -> None:
        for sid in reversed(self._start_order):
            instance = self._instances.get(sid)
            if instance is not None:
                await self._stop_instance(instance)
                self._on_instance_removed(instance)
        self._instances.clear()
        self._instance_fingerprints.clear()
        self._start_order.clear()

    async def _refresh_instances(self) -> None:
        await asyncio.gather(*(self._refresh_instance(inst) for inst in self._instances.values()))

    def _create_instance(self, descriptor: D) -> S:
        raise NotImplementedError

    async def _start_instance(self, instance: S) -> None:
        pass

    async def _stop_instance(self, instance: S) -> None:
        pass

    async def _refresh_instance(self, instance: S) -> None:
        pass

    def _on_instance_added(self, instance: S, sid: str, descriptor: D) -> None:
        pass

    def _on_instance_removed(self, instance: S) -> None:
        pass


class ServiceInstanceRegistry:
    def __init__(self) -> None:
        self._by_class: dict[type, object] = {}
        self._by_id: dict[str, object] = {}

    def __setitem__(self, key: type | str, value: object) -> None:
        if isinstance(key, str):
            self._by_id[key] = value
        else:
            self._by_class[key] = value

    def __getitem__(self, key: type[Any]) -> Any:
        return self._by_class[key]

    def get(self, key: type[Any]) -> Any | None:
        return self._by_class.get(key)

    def get_by_id(self, descriptor_id: str) -> object | None:
        return self._by_id.get(descriptor_id)

    def get_all(self, base: type[Any]) -> list[Any]:
        result: list[Any] = []
        seen: set[int] = set()
        for inst in self._by_class.values():
            if isinstance(inst, base) and id(inst) not in seen:
                result.append(inst)
                seen.add(id(inst))
        for inst in self._by_id.values():
            if isinstance(inst, base) and id(inst) not in seen:
                result.append(inst)
                seen.add(id(inst))
        return result

    def require(self, key: type[Any]) -> Any:
        value = self._by_class.get(key)
        if value is None:
            raise KeyError(f"AbstractService {key.__name__} not registered")
        return value

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


class ServiceInstanceManager(InstanceManager[ServiceDescriptor, AbstractService]):
    def __init__(self, python_source: Any, config: Any, registry: ServiceInstanceRegistry) -> None:
        super().__init__(python_source)
        self._config = config
        self._registry = registry

    def _create_instance(self, descriptor: ServiceDescriptor) -> AbstractService:
        return descriptor.service_cls(config=self._config)

    async def _start_instance(self, instance: AbstractService) -> None:
        await await_if_needed(instance.start())

    async def _stop_instance(self, instance: AbstractService) -> None:
        await await_if_needed(instance.stop())

    async def _refresh_instance(self, instance: AbstractService) -> None:
        await await_if_needed(instance.refresh())

    def _on_instance_added(self, instance: AbstractService, sid: str, descriptor: ServiceDescriptor) -> None:
        self._registry[sid] = instance
        self._registry[descriptor.service_cls] = instance

    def _on_instance_removed(self, instance: AbstractService) -> None:
        self._registry.remove_by_instance(instance)


class ActiveInstanceServiceManager(ServiceInstanceManager):
    _cls: type[AbstractService]
    _attribute: str
    _prefix: str = 'provider'
    active_field: ConfigField[str | None]

    def __init__(self, config: Config, registry: ServiceInstanceRegistry) -> None:
        source = PythonProviderSource(self._cls, self._attribute, self._prefix)
        super().__init__(source, config, registry)
        self._active_id: str | None = None

    async def refresh(self) -> None:
        await super().refresh()
        self._select_active()

    def _select_active(self) -> None:
        configured = self._config.get(self.active_field)
        if configured is not None:
            if configured in self._instances:
                self._active_id = configured
                return
            if self._config.has_override(self.active_field):
                raise RuntimeError(f"Active {self._prefix} '{configured}' not found")
        if self._active_id is not None and self._active_id in self._instances:
            return
        if self._instances:
            self._active_id = next(iter(self._instances))

    @property
    def _active(self) -> Any | None:
        if self._active_id is None:
            raise RuntimeError(f"No active {self._prefix}")
        return self._instances.get(self._active_id)


class CustomInstanceServiceManager(ServiceInstanceManager):
    def __init__(self, config: Any, registry: ServiceInstanceRegistry) -> None:
        source = PythonServiceSource()
        super().__init__(source, config, registry)
