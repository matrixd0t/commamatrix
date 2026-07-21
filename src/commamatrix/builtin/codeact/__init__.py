# builtin/codeact/__init__.py

"""CodeAct plugin — optional-by-import Python execution with virtual tool modules.

Importing this package makes CodeAct available as a Service.
The ``CodeActService`` is discovered automatically and managed by the agent's service lifecycle when added via ``agent.add_extensions``.
"""

from __future__ import annotations

from ...components.tool import ToolDescriptor


def is_codeact_internal(descriptor: ToolDescriptor) -> bool:
    """Return True if the descriptor belongs to a CodeAct control tool."""
    return bool(descriptor.meta.get("codeact"))


from . import hooks, tools, service


__all__ = ['hooks', 'tools', 'service', 'is_codeact_internal']
