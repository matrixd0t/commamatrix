# core/manager.py

from __future__ import annotations

import hashlib
import weakref
from collections.abc import Callable, ValuesView
from typing import Generic, TypeVar

from ..extensions import (
    Descriptor,
    Source,
    UnavailableSourceError,
    StaleDescriptorError,
)
from ..api.service import AbstractService
from ..api.utils import await_if_needed


D = TypeVar("D", bound=Descriptor)


class Manager(AbstractService, Generic[D]):
    """Manages sources, descriptors, indexes, and invalidation.

    Scan() rescans all mounted sources and rebuilds internal indexes
    when the descriptor set changes. Notifies on_change callback when
    descriptors change.
    """

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
