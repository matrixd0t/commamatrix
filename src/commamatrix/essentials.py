# essentials.py

"""Recommended built-in extensions for a standard CommaMatrix agent.

The Agent class loads these by default (``essentials=True``).
Users can call ``setup(agent)`` directly or opt out via ``Agent(essentials=False)``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core.agent import Agent


def _prefix() -> str:
    parts = __name__.split(".")
    return ".".join(parts[: parts.index("commamatrix") + 1])


async def setup(agent: Agent) -> None:
    """Load recommended built-in extensions into agent."""
    prefix = _prefix()
    to_add: list[str] = [
        prefix + ".builtin.llm_http_adapter",
        prefix + ".builtin.codeact",
        prefix + ".builtin.self_extension",
        prefix + ".builtin.web_utils",
        prefix + ".builtin.io_tools",
        prefix + ".builtin.multi_dialog",
    ]
    try:
        import bcrypt  # noqa: F401
        import jwt  # noqa: F401
        import starlette  # noqa: F401
        import uvicorn  # noqa: F401

        to_add.append(prefix + ".builtin.http_connector")
    except ImportError:
        print("Warning: HTTP dependencies are not installed. HTTP connector and Web UI are disabled. Install with: pip install commamatrix[http]")
    await agent.add_extensions(*to_add)
