# core/extension_manager.py

from __future__ import annotations

import hashlib
import inspect
import weakref
from collections.abc import Callable, ValuesView
from typing import Generic, TypeVar

from ..extensions import (
    ExtensionDescriptor,
    ExtensionSource,
    ExtensionUnavailableError,
    StaleExtensionError,
)


D = TypeVar("D", bound=ExtensionDescriptor)


class ExtensionManager(Generic[D]):
    """Manage extension sources, descriptors, indexes, and invalidation."""

    def __init__(self) -> None:
        self._sources: list[ExtensionSource[D]] = []
        self._descriptors: dict[str, D] = {}
        self._source_descriptor_ids: dict[int, set[str]] = {}
        self._source_invalidators: dict[int, Callable[[], None]] = {}
        self._fingerprint: str | None = None

    @property
    def descriptors(self) -> ValuesView[D]:
        """Live view of all currently registered descriptors."""
        return self._descriptors.values()

    def _source_of(self, descriptor: D) -> ExtensionSource[D]:
        """Return the live source after checking descriptor freshness."""
        self._ensure_current(descriptor)
        source = descriptor._source_ref()
        if source is None:
            raise ExtensionUnavailableError("ExtensionSource has been unloaded.")
        return source

    def _ensure_current(self, descriptor: D) -> None:
        current = self._descriptors.get(descriptor.id)
        if current is not descriptor:
            raise StaleExtensionError(
                f"Extension descriptor is no longer active: {descriptor.id}"
            )

        source = descriptor._source_ref()
        if source is None or not source.available:
            raise ExtensionUnavailableError(
                f"Extension source is unavailable: {descriptor.id}"
            )

    def is_current(self, descriptor: D) -> bool:
        """Return whether *descriptor* is still active in this manager."""
        try:
            self._ensure_current(descriptor)
        except (ExtensionUnavailableError, StaleExtensionError):
            return False
        return True

    def mount(self, source: ExtensionSource[D]) -> None:
        """Register a source without scanning it."""
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

    def unmount(self, source: ExtensionSource[D]) -> None:
        """Unregister a source and remove its active descriptors."""
        self.invalidate(source)
        invalidator = self._source_invalidators.pop(id(source), None)
        if invalidator is not None:
            source._detach_invalidator(invalidator)
        self._sources.remove(source)
        self._source_descriptor_ids.pop(id(source), None)

    async def start(self) -> None:
        """Restore and start all mounted sources."""
        for source in self._sources:
            source.restore()
            result = source.start()
            if inspect.isawaitable(result):
                await result

    async def stop(self) -> None:
        """Invalidate descriptors and stop all mounted sources."""
        for source in reversed(self._sources):
            source.invalidate()
            result = source.stop()
            if inspect.isawaitable(result):
                await result

    def invalidate(self, source: ExtensionSource[D]) -> bool:
        """Remove all active descriptors supplied by *source* immediately."""
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
        return True

    def scan(self) -> bool:
        """Rescan all sources and rebuild indexes when descriptors changed."""
        descriptors: dict[str, D] = {}
        source_descriptor_ids: dict[int, set[str]] = {}

        for source in self._sources:
            if not source.available:
                source_descriptor_ids[id(source)] = set()
                continue
            current_ids: set[str] = set()
            for descriptor in source.scan():
                if descriptor.id in descriptors:
                    raise ValueError(
                        f"Duplicate extension descriptor id: {descriptor.id}"
                    )
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
        return True

    def _calculate_fingerprint(self, descriptors: dict[str, D] | None = None) -> str:
        current = self._descriptors if descriptors is None else descriptors
        fingerprint = hashlib.sha256()
        for descriptor in sorted(current.values(), key=lambda item: item.id):
            fingerprint.update(descriptor.fingerprint.encode())
        return fingerprint.hexdigest()

    def _rebuild(self) -> None:
        """Rebuild specialized indexes after descriptors change."""
