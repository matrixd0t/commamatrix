# builtin/codeact/rpc/protocol.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, kw_only=True)
class RPCRequest:
    id: str
    method: str
    params: dict[str, Any] = field(default_factory=dict)


class RPCError(Exception):
    __slots__ = ('code', 'message', 'data')

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


@dataclass(slots=True, kw_only=True)
class RPCResponse:
    id: str
    result: Any = None
    error: RPCError | None = None
