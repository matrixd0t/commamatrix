# builtin/python/service_source.py

from __future__ import annotations

import weakref
from ...api.service import AbstractService, SERVICE_ATTRIBUTE, ServiceDescriptor
from .base_source import PythonSource


class PythonServiceSource(PythonSource[ServiceDescriptor]):
    """Discovers custom AbstractService subclasses via module scanning.

    Only concrete Service subclasses (like CodeActManager) are picked up —
    provider slots (Storage, FileStorage, LLMAdapter) no longer inherit
    from Service and therefore do not carry SERVICE_ATTRIBUTE.
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
        return ServiceDescriptor(
            id=f"service://{obj.__module__}/{object_name}",
            service_cls=obj,
            metadata={},
            _source_ref=weakref.ref(self),
        )
