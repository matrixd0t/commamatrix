# builtin/python/connector_source.py

from __future__ import annotations

import inspect
import weakref
from typing import Any, cast

from ...api.config import ConfigField
from ...api.connector import (
    CONNECTOR_ATTRIBUTE,
    CONNECTOR_MODULES,
    Connector,
    ConnectorDescriptor,
    ConnectorSource,
)
from .extension_source import PythonExtensionSource


class PythonConnectorSource(PythonExtensionSource[ConnectorDescriptor], ConnectorSource):

    @property
    def extension_modules(self) -> set[str]:
        return CONNECTOR_MODULES

    @property
    def marker_attribute(self) -> str:
        return CONNECTOR_ATTRIBUTE

    def build_descriptor(self, object_name: str, obj: object) -> ConnectorDescriptor | None:
        connector_cls = cast(type[Connector], obj)
        return ConnectorDescriptor(
            id=f"connector://{connector_cls.__module__}/{object_name}",
            connector_cls=connector_cls,
            metadata={},
            _source_ref=weakref.ref(self),
        )

    @staticmethod
    def instantiate(connector_cls: type[Connector], kwargs: dict | None = None) -> Connector:
        kwargs = dict(kwargs or {})
        sig = inspect.signature(connector_cls.__init__)
        for name, param in sig.parameters.items():
            if name in ('self', 'args', 'kwargs'):
                continue
            if name in kwargs:
                continue
            if isinstance(param.default, ConfigField):
                kwargs[name] = param.default.get()
        constructor = cast(Any, connector_cls)
        return constructor(**kwargs)
