# builtin/subagent/__init__.py

"""Headless subagent execution and internal result transport."""

from . import connector, hooks, service, tools
from .connector import InternalConnector, InternalOrigin
from .service import SubagentService
from .tools import call_agent

__all__ = [
    "InternalConnector",
    "InternalOrigin",
    "SubagentService",
    "call_agent",
]
