# core/extension_runtime.py

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Iterable, ValuesView
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar
import weakref


D = TypeVar("D", bound="ExtensionDescriptor")


class ExtensionSource(ABC, Generic[D]):
    """
    Abstract source of extensions.

    Subclasses implement `scan()` to discover and return available
    extensions (descriptors). Each source owns the lifecycle of its
    descriptors.
    """

    @abstractmethod
    def scan(self) -> Iterable[D]:
        """
        Return all currently available extension descriptors.
        Called by `ExtensionRuntime.scan()` to rebuild the global index.
        """
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ExtensionDescriptor:
    """
    Base immutable descriptor for any extension (tool, hook, resource, ...).

    Fields:
        id: Globally unique string identifier (e.g. ``python://ns/name``).
        _source_ref: Weak reference back to the `ExtensionSource` that
            created this descriptor.  Accessible via the `.source` property.
    """

    id: str

    _source_ref: weakref.ReferenceType[ExtensionSource] = field(repr=False)

    @property
    def source(self) -> ExtensionSource:
        """Return the ExtensionSource that owns this descriptor."""
        src = self._source_ref()
        if src is None:
            raise RuntimeError("ExtensionSource has been unloaded.")
        return src

    @property
    def fingerprint(self) -> str:
        """
        Deterministic hash of the descriptor's semantic content.

        Subclasses extend `_fingerprint_payload()` to include their own
        fields. The fingerprint is recomputed on every call (cheap) and
        used by `ExtensionRuntime.scan()` to detect changes without
        comparing descriptor objects directly.
        """
        payload = self._fingerprint_payload()
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _fingerprint_payload(self) -> dict[str, Any]:
        """
        Canonical serializable payload for the fingerprint.
        Override in subclasses to include relevant fields.
        """
        return {"id": self.id}


class ExtensionRuntime(Generic[D]):
    """
    Generic runtime that manages a set of sources and their descriptors.

    Responsibilities:
        - Hold a list of mounted `ExtensionSource` instances.
        - Periodically re-scan them via `scan()` to detect changes.
        - Maintain a global dict of descriptors keyed by `id`.
        - Rebuild internal indices via `_rebuild()` when the set changes.
    """

    def __init__(self) -> None:
        self._sources: list[ExtensionSource[D]] = []
        self._descriptors: dict[str, D] = {}
        self._fingerprint: str | None = None

    @property
    def descriptors(self) -> ValuesView[D]:
        """Live view of all currently registered descriptors."""
        return self._descriptors.values()

    def mount(self, source: ExtensionSource[D]) -> None:
        """Register a new extension source. Does NOT trigger a re-scan."""
        self._sources.append(source)

    def unmount(self, source: ExtensionSource[D]) -> None:
        """Unregister a source. Does NOT trigger a re-scan."""
        self._sources.remove(source)

    def scan(self) -> bool:
        """
        Re-scan all mounted sources and rebuild the descriptor index.

        Returns True if the descriptor set changed, False if nothing changed since the last scan.
        """
        descriptors: dict[str, D] = {}

        for source in self._sources:
            for descriptor in source.scan():
                descriptors[descriptor.id] = descriptor

        fingerprint = hashlib.sha256()
        for descriptor in sorted(descriptors.values(), key=lambda d: d.id):
            fingerprint.update(descriptor.fingerprint.encode())
        fingerprint = fingerprint.hexdigest()

        if fingerprint == self._fingerprint:
            return False

        self._descriptors = descriptors
        self._fingerprint = fingerprint

        self._rebuild()

        return True

    def _rebuild(self) -> None:
        """
        Rebuild internal indices after the descriptor set changed.
        Must be overridden by subclasses (e.g. BM25 index for tools,
        event → handlers map for hooks).
        """
        raise NotImplementedError
