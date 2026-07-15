# builtin/python/connector_source.py

from __future__ import annotations

import weakref
from typing import cast

from ...api.connector import (
    CONNECTOR_ATTRIBUTE,
    Connector,
    ConnectorDescriptor,
    ConnectorSource,
)
from .base_source import PythonSource


class PythonConnectorSource(PythonSource[ConnectorDescriptor], ConnectorSource):
    """Python-backed connector source.

    Discovers Connector subclasses via module scanning.
    """

    def __init__(self) -> None:
        super().__init__()

    @property
    def marker_attribute(self) -> str:
        return CONNECTOR_ATTRIBUTE

    def build_descriptor(self, object_name: str, obj: object) -> ConnectorDescriptor | None:
        connector_cls = cast(type[Connector], obj)
        return ConnectorDescriptor(
            id=f"connector://{connector_cls.__module__}/{object_name}",
            service_cls=connector_cls,
            connector_cls=connector_cls,
            metadata={},
            _source_ref=weakref.ref(self),
        )
