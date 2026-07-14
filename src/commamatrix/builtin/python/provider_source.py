# builtin/python/provider_source.py

from __future__ import annotations

import weakref

from ...api.service import AbstractService, ServiceDescriptor
from .extension_source import PythonExtensionSource


class PythonProviderSource(PythonExtensionSource[ServiceDescriptor]):
    """Generic Python-backed source for service/provider descriptors.

    Discovers concrete subclasses of a given base type that carry
    the specified marker attribute. Returns ServiceDescriptor instances.
    """

    def __init__(self, base_type: type[AbstractService], marker_attribute: str, id_prefix: str) -> None:
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
