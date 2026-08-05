# builtin/subagent/__init__.py

"""Headless subagent execution and internal result transport."""

from . import connector, hooks, service, tools
from .connector import InternalConnector, InternalOrigin
from .service import SubagentService
from .submit import submit_run
from .tools import call_subagent

__all__ = [
    "InternalConnector",
    "InternalOrigin",
    "SubagentService",
    "call_subagent",
    "submit_run",
]
