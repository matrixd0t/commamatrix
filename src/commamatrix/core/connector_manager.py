# core/connector_manager.py

from __future__ import annotations

from .extension_manager import ExtensionManager
from ..api.connector import Connector, ConnectorDescriptor
from ..api.config import Config, connector_classes
from ..builtin.python.connector_source import PythonConnectorSource


class ConnectorManager(ExtensionManager[ConnectorDescriptor]):
    """
    Manager for connector descriptors.

    Holds auto-discovered descriptors and their instances.
    Instances are populated by ``resolve()`` which merges provided
    instances with auto-instantiated ones from descriptors.
    """

    def __init__(self) -> None:
        super().__init__()
        self.mount(PythonConnectorSource())

    def resolve(self, config: Config) -> list[Connector]:
        """Return final connector list from config or auto-discovery."""
        classes = config.get(connector_classes)
        if classes is not None:
            return [cls(config=config) for cls in classes]
        return [
            descriptor.connector_cls(config=config) for descriptor in self.descriptors
        ]
