# src/commamatrix/builtin/mcp/server.py

from __future__ import annotations

import logging
import weakref
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ...core.classes.descriptor import Descriptor
from ...core.classes.manager import InstanceManager
from ...core.classes.source import Source
from .config import MCPServerSpec
from .runtime import MCPDependencyError, MCPServerRuntime

if TYPE_CHECKING:
    from .manager import MCPService


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MCPServerDescriptor(Descriptor):
    """Declarative description of one configured MCP server."""

    spec: MCPServerSpec

    @staticmethod
    def id_for(server_id: str) -> str:
        return f"mcp-server://{quote(server_id, safe='')}"

    def _fingerprint_payload(self) -> dict[str, Any]:
        from .config import server_spec_to_value

        return {
            "id": self.id,
            "spec": server_spec_to_value(self.spec),
        }


class MCPServerSource(Source[MCPServerDescriptor]):
    """Builds server descriptors from all loaders registered on MCPService."""

    def __init__(self, service: MCPService) -> None:
        super().__init__()
        self.service = service

    def scan(self) -> list[MCPServerDescriptor]:
        descriptors: list[MCPServerDescriptor] = []
        seen: set[str] = set()
        for spec in self.service._load_specs():
            descriptor_id = MCPServerDescriptor.id_for(spec.server_id)
            if descriptor_id in seen:
                raise ValueError(f"Duplicate MCP server ID: {spec.server_id!r}")
            seen.add(descriptor_id)
            descriptors.append(
                MCPServerDescriptor(
                    id=descriptor_id,
                    spec=spec,
                    _source_ref=weakref.ref(self),
                )
            )
        return descriptors


class MCPServerManager(InstanceManager[MCPServerDescriptor, MCPServerRuntime]):
    """Reconciles MCP server descriptors with live server runtimes."""

    def __init__(self, service: MCPService) -> None:
        self.service = service
        source = MCPServerSource(service)
        super().__init__(service.agent, python_source=source)

    def _create_instance(self, descriptor: MCPServerDescriptor) -> MCPServerRuntime:
        return MCPServerRuntime(
            self.agent,
            descriptor.spec,
            self.service._request_refresh,
            self.service.client_name,
            self.service.client_version,
        )

    async def _start_instance(self, instance: MCPServerRuntime) -> bool:
        try:
            await instance.start()
        except MCPDependencyError:
            raise
        except Exception:
            logger.warning(
                "MCP server %r failed to start and will be skipped",
                instance.spec.server_id,
                exc_info=True,
            )
            try:
                await instance.stop()
            except Exception:
                logger.exception(
                    "Failed to clean up MCP server %r after a startup error",
                    instance.spec.server_id,
                )
            return False
        return True

    async def _stop_instance(self, instance: MCPServerRuntime) -> None:
        await instance.stop()

    async def _refresh_instance(self, instance: MCPServerRuntime) -> None:
        await instance.refresh()

    def get_by_server_id(self, server_id: str) -> MCPServerRuntime | None:
        return self.get_by_id(MCPServerDescriptor.id_for(server_id))

    def iter_servers(self):
        for descriptor in self.descriptors:
            runtime = self.get_by_id(descriptor.id)
            if runtime is not None:
                yield descriptor.spec, runtime


__all__ = [
    "MCPServerDescriptor",
    "MCPServerSource",
    "MCPServerManager",
]
