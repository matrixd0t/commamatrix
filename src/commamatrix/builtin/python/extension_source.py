# builtin/python/extension_source.py

from __future__ import annotations

import inspect
import sys
from abc import abstractmethod
from collections.abc import Iterable
from typing import Generic, TypeVar

from ...core.extension_runtime import ExtensionDescriptor, ExtensionSource


D = TypeVar("D", bound=ExtensionDescriptor)


class PythonExtensionSource(ExtensionSource[D], Generic[D]):
    """
    Base class for Python-backed extension sources.

    Scans registered Python modules for objects marked with a specific
    attribute and delegates descriptor construction to subclasses.
    """

    @property
    @abstractmethod
    def extension_modules(self) -> set[str]:
        ...

    @property
    @abstractmethod
    def marker_attribute(self) -> str:
        ...

    @abstractmethod
    def build_descriptor(self, object_name: str, obj: object) -> D | None:
        ...

    def iter_objects(self) -> Iterable[tuple[str, object]]:
        for module_name in sorted(self.extension_modules):
            module = sys.modules.get(module_name)
            if module is None:
                continue

            for object_name, obj in inspect.getmembers(module):
                if hasattr(obj, self.marker_attribute):
                    yield object_name, obj

    def scan(self) -> list[D]:
        descriptors: list[D] = []

        for name, obj in self.iter_objects():
            descriptor = self.build_descriptor(name, obj)
            if descriptor is not None:
                descriptors.append(descriptor)

        return descriptors
