# builtin/python/connector_source.py

from __future__ import annotations

import weakref
from typing import cast

from ...api.connector import (
    CONNECTOR_ATTRIBUTE,
    CONNECTOR_MODULES,
    Connector,
    ConnectorDescriptor,
    ConnectorSource,
)
from .extension_source import PythonExtensionSource


class PythonConnectorSource(
    PythonExtensionSource[ConnectorDescriptor], ConnectorSource
):
    @property
    def extension_modules(self) -> set[str]:
        return CONNECTOR_MODULES

    @property
    def marker_attribute(self) -> str:
        return CONNECTOR_ATTRIBUTE

    def build_descriptor(
        self, object_name: str, obj: object
    ) -> ConnectorDescriptor | None:
        connector_cls = cast(type[Connector], obj)
        return ConnectorDescriptor(
            id=f"connector://{connector_cls.__module__}/{object_name}",
            connector_cls=connector_cls,
            metadata={},
            _source_ref=weakref.ref(self),
        )
