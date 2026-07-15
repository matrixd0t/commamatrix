# builtin/python/base_source.py

from __future__ import annotations

import sys
from abc import abstractmethod
from collections.abc import Iterable
from typing import Generic, TypeVar

from ...extensions import Descriptor, Source


D = TypeVar("D", bound=Descriptor)


class PythonSource(Source[D], Generic[D]):
    """
    Base class for Python-backed extension sources.

    Scans modules from a caller-provided scope set for objects marked
    with a specific attribute. Only objects whose __module__ matches the
    scanned module name are considered — re-exports are ignored.
    Subclasses define marker_attribute and build_descriptor.
    """

    def __init__(self) -> None:
        super().__init__()
        self._scope: list[str] = []

    def set_scope(self, scope: list[str]) -> None:
        self._scope = scope

    @property
    @abstractmethod
    def marker_attribute(self) -> str: ...

    @abstractmethod
    def build_descriptor(self, object_name: str, obj: object) -> D | None: ...

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
