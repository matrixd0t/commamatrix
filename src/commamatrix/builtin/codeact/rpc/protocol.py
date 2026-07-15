# builtin/codeact/rpc/protocol.py

"""RPC message dataclasses: request, response and error."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Namespace(StrEnum):
    CONTEXT = "context"
    TOOLS = "tools"


class ContextField(StrEnum):
    RUN = "run"
    TOOL_CALL = "tool_call"
    META = "meta"
    STORAGE = "storage"


class StorageMethod(StrEnum):
    SAVE_EVENT = "save_event"
    GET_BRANCH = "get_branch"
    FIND_ITEM_ID_BY_EXTERNAL_ID = "find_item_id_by_external_id"


class ToolsMethod(StrEnum):
    INVOKE = "invoke"
    SEARCH = "search"
    SCHEMAS = "schemas"
    RESOLVE = "resolve"
    ALIASES = "aliases"
    LIST = "list"


@dataclass(slots=True, kw_only=True)
class RPCRequest:
    """Outbound RPC call from client to server."""

    id: str
    method: str
    params: dict[str, Any] = field(default_factory=dict)


class RPCError(Exception):
    """Structured RPC error with a numeric code, message and optional data."""

    __slots__ = ('code', 'message', 'data')

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
