# core/connector_runtime.py

from __future__ import annotations

from typing import TYPE_CHECKING

from .extension_runtime import ExtensionRuntime
from ..api.connector import Connector, ConnectorDescriptor
from ..builtin.python.connector_source import PythonConnectorSource

if TYPE_CHECKING:
    from ..api.hooks import OnParsedCtx
    from ..core.agent import Agent


class ConnectorRuntime(ExtensionRuntime[ConnectorDescriptor]):
    """
    Runtime for connector descriptors.

    Holds auto-discovered descriptors and their instances.
    Instances are populated by ``resolve()`` which merges provided
    instances with auto-instantiated ones from descriptors.
    """

    def resolve(self, provided: list[Connector]) -> list[Connector]:
        """Return final connector list: provided instances + auto-instantiated for missing classes."""
        result = list(provided)
        provided_types = {type(c) for c in provided}
        for descriptor in self.descriptors:
            connector_cls = descriptor.connector_cls
            if connector_cls not in provided_types:
                result.append(PythonConnectorSource.instantiate(connector_cls))
        return result

    @staticmethod
    async def parse_any(instances: list[Connector], data: dict, agent: Agent) -> OnParsedCtx | None:
        for connector in instances:
            if ctx := await connector.parse(data, agent):
                return ctx
        return None

    def _rebuild(self) -> None:
        return None
