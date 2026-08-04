# builtin/codeact/__init__.py

"""CodeAct plugin — optional-by-import Python execution with virtual tool modules.

Importing this package makes CodeAct available as a Service.
The ``CodeActService`` is discovered automatically and managed by the agent's service lifecycle when added via ``agent.add_extensions``.
"""

from __future__ import annotations
from . import hooks, tools, instructions, service
from .hooks import codeact_enabled
from .service import (
    backend_cls,
    searcher_cls,
    execution_timeout,
    rpc_timeout,
    shutdown_timeout,
    max_output_bytes,
    max_search_results,
    max_tools_list,
)

__all__ = [
    "hooks",
    "tools",
    "instructions",
    "service",
    "codeact_enabled",
    "backend_cls",
    "searcher_cls",
    "execution_timeout",
    "rpc_timeout",
    "shutdown_timeout",
    "max_output_bytes",
    "max_search_results",
    "max_tools_list",
]
