# builtin/python/file_storage_source.py

from __future__ import annotations

import weakref
from typing import cast

from ...api.file_storage import FILE_STORAGE_ATTRIBUTE, FILE_STORAGE_MODULES, FileStorage
from ...api.provider import ProviderDescriptor, ProviderSource
from .extension_source import PythonExtensionSource


class PythonFileStorageSource(PythonExtensionSource[ProviderDescriptor], ProviderSource):
    """Discovers FileStorage subclasses registered via __init_subclass__."""

    def __init__(self) -> None:
        super().__init__()
        self._by_module: dict[str, list[ProviderDescriptor]] = {}

    def scan(self) -> list[ProviderDescriptor]:
        self._by_module.clear()
        return super().scan()

    @property
    def extension_modules(self) -> set[str]:
        if self._scope:
            return self._scope
        return FILE_STORAGE_MODULES

    @property
    def marker_attribute(self) -> str:
        return FILE_STORAGE_ATTRIBUTE

    def build_descriptor(self, object_name: str, obj: object) -> ProviderDescriptor | None:
        cls = cast(type[FileStorage], obj)
        if not (isinstance(cls, type) and issubclass(cls, FileStorage)):
            return None
        descriptor = ProviderDescriptor(
            id=f"file_storage://{cls.__module__}/{object_name}",
            service_cls=cls,
            metadata={},
            _source_ref=weakref.ref(self),
        )
        self._by_module.setdefault(cls.__module__, []).append(descriptor)
        return descriptor

    def descriptors_for_module(self, module_name: str) -> list[ProviderDescriptor]:
        return list(self._by_module.get(module_name, []))

    def remove_module(self, module_name: str) -> None:
        self._by_module.pop(module_name, None)
