# builtin/python/service_source.py

from __future__ import annotations

import weakref
from ...api.service import AbstractService, SERVICE_ATTRIBUTE, ServiceDescriptor
from ...api.storage import STORAGE_ATTRIBUTE
from ...api.file_storage import FILE_STORAGE_ATTRIBUTE
from ...api.llm_adapter import LLM_ADAPTER_ATTRIBUTE
from ...core.extension_manager import ExtensionManager
from .extension_source import PythonExtensionSource


class PythonServiceSource(PythonExtensionSource[ServiceDescriptor]):
    """Discovers AbstractService subclasses via module scanning.

    Provider slots are filtered out by checking for provider-specific
    marker attributes since they are managed by dedicated provider managers.
    """

    def __init__(self) -> None:
        super().__init__()

    @property
    def marker_attribute(self) -> str:
        return SERVICE_ATTRIBUTE

    def build_descriptor(self, object_name: str, obj: object) -> ServiceDescriptor | None:
        if not (isinstance(obj, type) and issubclass(obj, AbstractService)):
            return None
        if getattr(obj, "__abstractmethods__", None):
            return None
        if issubclass(obj, ExtensionManager):
            return None
        provider_markers = (STORAGE_ATTRIBUTE, FILE_STORAGE_ATTRIBUTE, LLM_ADAPTER_ATTRIBUTE)
        if any(getattr(obj, m, False) for m in provider_markers):
            return None
        return ServiceDescriptor(
            id=f"service://{obj.__module__}/{object_name}",
            service_cls=obj,
            metadata={},
            _source_ref=weakref.ref(self),
        )
