# builtin/codeact/__init__.py

"""CodeAct plugin — optional-by-import Python execution with virtual tool modules.

Importing this package makes CodeAct available as a Service.
The ``CodeActService`` is discovered automatically and managed by the agent's service lifecycle when added via ``agent.add_extensions``.
"""

from __future__ import annotations

from . import hooks, instructions, service, tools
from .hooks import codeact_enabled
from .service import (
    codeact_backend,
    codeact_execution_timeout,
    codeact_max_output_bytes,
    codeact_max_search_results,
    codeact_max_tools_list,
    codeact_rpc_timeout,
    codeact_searcher,
    codeact_shutdown_timeout,
)

__all__ = [
    "codeact_backend",
    "codeact_enabled",
    "codeact_execution_timeout",
    "codeact_max_output_bytes",
    "codeact_max_search_results",
    "codeact_max_tools_list",
    "codeact_rpc_timeout",
    "codeact_searcher",
    "codeact_shutdown_timeout",
    "hooks",
    "instructions",
    "service",
    "tools",
]
