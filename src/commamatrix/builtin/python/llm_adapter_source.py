# builtin/python/llm_adapter_source.py

from __future__ import annotations

import weakref
from typing import cast

from ...api.llm_adapter import (
    LLM_ADAPTER_ATTRIBUTE,
    LLM_ADAPTER_MODULES,
    LLMAdapter,
)
from ...api.provider import ProviderDescriptor, ProviderSource
from .extension_source import PythonExtensionSource


class PythonLLMAdapterSource(PythonExtensionSource[ProviderDescriptor], ProviderSource):
    """Discovers LLMAdapter subclasses registered via __init_subclass__."""

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
        return LLM_ADAPTER_MODULES

    @property
    def marker_attribute(self) -> str:
        return LLM_ADAPTER_ATTRIBUTE

    def build_descriptor(self, object_name: str, obj: object) -> ProviderDescriptor | None:
        cls = cast(type[LLMAdapter], obj)
        if not (isinstance(cls, type) and issubclass(cls, LLMAdapter)):
            return None
        descriptor = ProviderDescriptor(
            id=f"llm_adapter://{cls.__module__}/{object_name}",
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
