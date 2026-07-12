# extensions/contracts.py

from __future__ import annotations

import hashlib
import json
import weakref
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, cast


D = TypeVar("D", bound="ExtensionDescriptor")
InvalidationCallback = Callable[[], None]


class ExtensionSource(ABC, Generic[D]):
    """Discover extensions and notify managers when a source becomes unavailable."""

    def __init__(self) -> None:
        self._invalidation_callbacks: list[InvalidationCallback] = []
        self._available = True

    @property
    def available(self) -> bool:
        """Whether descriptors from this source may currently be used."""
        return getattr(self, "_available", True)

    @abstractmethod
    def scan(self) -> Iterable[D]:
        """Return currently available extension descriptors."""
        raise NotImplementedError

    async def start(self) -> None:
        """Start source-owned resources before discovery."""

    async def stop(self) -> None:
        """Stop source-owned resources after descriptors are invalidated."""

    def invalidate(self) -> None:
        """Invalidate descriptors currently provided by this source."""
        self._available = False
        callbacks = cast(
            tuple[InvalidationCallback, ...],
            tuple(getattr(self, "_invalidation_callbacks", ())),
        )
        for callback in callbacks:
            callback()

    def restore(self) -> None:
        """Allow the next manager scan to discover this source again."""
        self._available = True

    def _attach_invalidator(self, callback: InvalidationCallback) -> None:
        callbacks = getattr(self, "_invalidation_callbacks", None)
        if callbacks is None:
            callbacks = self._invalidation_callbacks = []
        if callback not in callbacks:
            callbacks.append(callback)

    def _detach_invalidator(self, callback: InvalidationCallback) -> None:
        callbacks = getattr(self, "_invalidation_callbacks", None)
        if callbacks is not None and callback in callbacks:
            callbacks.remove(callback)


@dataclass(frozen=True, slots=True)
class ExtensionDescriptor:
    """Immutable, source-independent description of an extension."""

    id: str
    _source_ref: weakref.ReferenceType[ExtensionSource] = field(repr=False)

    @property
    def fingerprint(self) -> str:
        """Return a deterministic hash of the descriptor's semantic content."""
        encoded = json.dumps(
            self._fingerprint_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {"id": self.id}
