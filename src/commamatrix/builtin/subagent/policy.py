# builtin/subagent/policy.py

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from ...components.tool import ToolDescriptor

ALLOWED_TOOLS_STATE_KEY = "allowed_tools"


def validate_allowed_tools(value: str | None) -> str | None:
    if value == "all" or value is None:
        return value
    re.compile(value)
    return value


def is_tool_allowed(run: Any, public_name: str) -> bool:
    if ALLOWED_TOOLS_STATE_KEY not in run.chain_state:
        return True
    allowed = run.chain_state[ALLOWED_TOOLS_STATE_KEY]
    if allowed == "all":
        return True
    if allowed is None:
        return False
    return re.fullmatch(str(allowed), public_name) is not None


def filter_tool_descriptors(run: Any, descriptors: Iterable[ToolDescriptor]) -> list[ToolDescriptor]:
    manager = run.agent.tool_manager
    return [d for d in descriptors if is_tool_allowed(run, manager.public_name(d))]


__all__ = [
    "ALLOWED_TOOLS_STATE_KEY",
    "filter_tool_descriptors",
    "is_tool_allowed",
    "validate_allowed_tools",
]
