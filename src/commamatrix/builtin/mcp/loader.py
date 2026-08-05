# src/commamatrix/builtin/mcp/loader.py

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from .config import (
    MCPServerSpec,
    mcp_config_path,
    normalize_server_specs,
    server_spec_to_value,
)

if TYPE_CHECKING:
    from ...core.agent.agent import Agent


class MCPConfigLoader(ABC):
    """Loads MCP server specifications from an external configuration source."""

    @abstractmethod
    def load(self, agent: Agent) -> list[MCPServerSpec]:
        """Load all MCP servers represented by this source."""

    def fingerprint(self, agent: Agent) -> str:
        """Return a SHA-256 fingerprint for the effective loaded servers."""
        payload = [server_spec_to_value(spec) for spec in self.load(agent)]
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def paths(self, agent: Agent) -> tuple[Path, ...]:
        """Return files represented by this loader for user-facing instructions."""
        return ()

    def describe(self, agent: Agent) -> str:
        """Return a stable identity used in the aggregate fingerprint."""
        return f"{type(self).__module__}.{type(self).__qualname__}"


class MCPJsonConfigLoader(MCPConfigLoader):
    """Loads the standard host-style ``mcpServers`` JSON configuration."""

    def path(self, agent: Agent) -> Path:
        configured = Path(agent.config.get(mcp_config_path))
        return configured if configured.is_absolute() else Path.cwd() / configured

    def ensure_file(self, agent: Agent) -> Path:
        path = self.path(agent)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            try:
                with path.open("x", encoding="utf-8") as stream:
                    json.dump({"mcpServers": {}}, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
            except FileExistsError:
                pass
        return path

    def load(self, agent: Agent) -> list[MCPServerSpec]:
        path = self.path(agent)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(normalize_server_specs(data))

    def fingerprint(self, agent: Agent) -> str:
        path = self.path(agent)
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            content = b"<missing>"
        return hashlib.sha256(content).hexdigest()

    def paths(self, agent: Agent) -> tuple[Path, ...]:
        return (self.path(agent),)

    def describe(self, agent: Agent) -> str:
        return f"{type(self).__module__}.{type(self).__qualname__}:{self.path(agent)}"


__all__ = ["MCPConfigLoader", "MCPJsonConfigLoader"]
