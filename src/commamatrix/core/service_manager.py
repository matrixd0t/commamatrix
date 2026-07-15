# core/service_manager.py

from __future__ import annotations

from typing import Any

from ..api.service import AbstractService, ServiceDescriptor
from ..api.utils import await_if_needed
from ..builtin.python.service_source import PythonServiceSource
from .instance_manager import InstanceManager


__all__ = ["ServiceRegistry", "ServiceInstanceManager", "CustomServiceManager"]


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
            raise KeyError(f"AbstractService {key.__name__} not registered")
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


class ServiceInstanceManager(InstanceManager[ServiceDescriptor, AbstractService]):
    """InstanceManager specialized for AbstractService lifecycle.

    Creates, starts, stops, and refreshes AbstractService instances.
    Integrates with ServiceRegistry for typed instance lookup.
    """

    def __init__(self, python_source: Any, config: Any, registry: ServiceRegistry) -> None:
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


class CustomServiceManager(ServiceInstanceManager):
    """Discover and manage custom AbstractService subclasses.

    Only concrete Service subclasses (like CodeActManager) are picked up —
    provider slots (Storage, FileStorage, LLMAdapter) no longer inherit
    from Service and therefore do not carry SERVICE_ATTRIBUTE.
    """

    def __init__(self, config: Any, registry: ServiceRegistry) -> None:
        source = PythonServiceSource()
        super().__init__(source, config, registry)
