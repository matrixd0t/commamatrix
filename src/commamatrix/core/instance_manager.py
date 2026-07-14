# core/instance_manager.py

from __future__ import annotations

import asyncio
from typing import Generic, TypeVar

from ..api.service import AbstractService
from ..extensions import ExtensionDescriptor, ExtensionSource
from .extension_manager import ExtensionManager


D = TypeVar("D", bound=ExtensionDescriptor)
I = TypeVar("I", bound=AbstractService)


class ExtensionInstanceManager(ExtensionManager[D], Generic[D, I]):
    """ExtensionManager that manages runtime instances tied to descriptors.

    Handles creation, fingerprint-based restart, stop, and cleanup
    for any type of instance. Subclasses implement _create_instance,
    _start_instance, _stop_instance, and _refresh_instance hooks.
    """

    def __init__(self, python_source: ExtensionSource[D]) -> None:
        super().__init__()
        self._python_source = python_source
        self.mount(self._python_source)
        self._instances: dict[str, I] = {}
        self._instance_fingerprints: dict[str, str] = {}
        self._start_order: list[str] = []

    def set_scope(self, scope: list[str]) -> None:
        self._python_source.set_scope(scope)

    @property
    def instances(self) -> list[I]:
        return [self._instances[sid] for sid in self._start_order if sid in self._instances]

    def get_by_id(self, descriptor_id: str) -> I | None:
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

    def _create_instance(self, descriptor: D) -> I:
        raise NotImplementedError

    async def _start_instance(self, instance: I) -> None:
        pass

    async def _stop_instance(self, instance: I) -> None:
        pass

    async def _refresh_instance(self, instance: I) -> None:
        pass

    def _on_instance_added(self, instance: I, sid: str, descriptor: D) -> None:
        pass

    def _on_instance_removed(self, instance: I) -> None:
        pass
