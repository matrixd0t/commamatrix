# builtin/codeact/rpc/protocol.py

"""RPC message dataclasses: request, response and error."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Namespace(StrEnum):
    TOOLS = "tools"


class ToolsMethod(StrEnum):
    INVOKE = "invoke"
    RESOLVE = "resolve"


@dataclass(slots=True, kw_only=True)
class RPCRequest:
    """Outbound RPC call from client to server."""

    id: str
    method: str
    params: dict[str, Any] = field(default_factory=dict)


class RPCError(Exception):
    """Structured RPC error with a numeric code, message and optional data."""

    __slots__ = ("code", "message", "data")

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


@dataclass(slots=True, kw_only=True)
class RPCResponse:
    """RPC reply carrying either a result or an error."""

    id: str
    result: Any = None
    error: RPCError | None = None
