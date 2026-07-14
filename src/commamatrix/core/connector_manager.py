# core/connector_manager.py

from __future__ import annotations

from .service_manager import ServiceInstanceManager, ServiceRegistry
from ..api.connector import Connector, ConnectorDescriptor, OnEvent
from ..api.config import Config
from ..builtin.python.connector_source import PythonConnectorSource


class ConnectorManager(ServiceInstanceManager):
    """Manager for connector descriptors with listener ownership.

    Owns connector instances and their listener tasks.
    Reconciliation creates new connectors, stops removed ones,
    and restarts changed ones. Listener lifecycle is automatic
    via Connector.start() / stop() (AbstractService contract).
    """

    def __init__(self, config: Config, registry: ServiceRegistry, on_event: OnEvent | None = None) -> None:
        source = PythonConnectorSource()
        super().__init__(source, config, registry)
        self._on_event = on_event

    def bind(self, on_event: OnEvent) -> None:
        self._on_event = on_event

    def resolve(self) -> list[Connector]:
        """Return all active connector instances."""
        return self.instances

    def _create_instance(self, descriptor: ConnectorDescriptor) -> Connector:
        connector = descriptor.connector_cls(config=self._config)
        connector._on_event = self._on_event
        return connector
