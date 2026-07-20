# core/classes/source.py

from __future__ import annotations

import sys
import weakref
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from typing import Generic, TypeVar, cast

from .descriptor import Descriptor
from .service import AbstractService, SERVICE_ATTRIBUTE, ServiceDescriptor

D = TypeVar("D", bound=Descriptor)
InvalidationCallback = Callable[[], None]


class UnavailableSourceError(RuntimeError):
    pass


class Source(Generic[D], ABC):
    """
    Base for discovery mechanism.
    Subclasses define how descriptors are produced.
    Invalidation notifies managers when a source becomes stale.
    """

    def __init__(self) -> None:
        self._invalidation_callbacks: list[InvalidationCallback] = []
        self._available = True

    @property
    def available(self) -> bool:
        return getattr(self, "_available", True)

    @abstractmethod
    def scan(self) -> Iterable[D]:
        raise NotImplementedError

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def invalidate(self) -> None:
        self._available = False
        callbacks = cast(
            tuple[InvalidationCallback, ...],
            tuple(getattr(self, "_invalidation_callbacks", ())),
        )
        for callback in callbacks:
            callback()

    def restore(self) -> None:
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


class PythonSource(Source[D], Generic[D]):
    """
    Scoped module scanning.
    Iterates vars() for objects with marker_attribute, filtering out private names and cross-module re-exports by __module__ check.
    """

    def __init__(self) -> None:
        super().__init__()
        self._scope: list[str] = []

    def set_scope(self, scope: list[str]) -> None:
        self._scope = scope

    @property
    @abstractmethod
    def marker_attribute(self) -> str:
        ...

    @abstractmethod
    def build_descriptor(self, object_name: str, obj: object) -> D | None:
        ...

    def iter_objects(self) -> Iterable[tuple[str, object]]:
        for module_name in self._scope:
            module = sys.modules.get(module_name)
            if module is None:
                continue
            for object_name, obj in vars(module).items():
                if object_name.startswith("_"):
                    continue
                if not hasattr(obj, self.marker_attribute):
                    continue
                if getattr(obj, "__module__", None) != module_name:
                    continue
                yield object_name, obj

    def scan(self) -> list[D]:
        descriptors: list[D] = []
        for name, obj in self.iter_objects():
            descriptor = self.build_descriptor(name, obj)
            if descriptor is not None:
                descriptors.append(descriptor)
        return descriptors


class PythonServiceSource(PythonSource[ServiceDescriptor]):
    """Unified service source for marker-driven discovery. Configurable
    via base_type, marker_attribute, and id_prefix to support provider
    slots (LLMAdapter, Storage, FileStorage) alongside plain Service."""

    def __init__(self, base_type: type[AbstractService] = AbstractService, marker_attribute: str = SERVICE_ATTRIBUTE, id_prefix: str = "service") -> None:
        super().__init__()
        self._base_type = base_type
        self._marker = marker_attribute
        self._id_prefix = id_prefix

    @property
    def marker_attribute(self) -> str:
        return self._marker

    def build_descriptor(self, object_name: str, obj: object) -> ServiceDescriptor | None:
        if not (isinstance(obj, type) and issubclass(obj, self._base_type)):
            return None
        if getattr(obj, "__abstractmethods__", None):
            return None
        return ServiceDescriptor(
            id=f"{self._id_prefix}://{obj.__module__}/{object_name}",
            service_cls=obj,
            metadata={},
            _source_ref=weakref.ref(self),
        )
