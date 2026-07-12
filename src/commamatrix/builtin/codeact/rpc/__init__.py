# builtin/codeact/rpc/__init__.py

"""JSON-RPC protocol for parent ↔ child communication in CodeAct subprocesses."""

from .protocol import RPCRequest, RPCResponse, RPCError
from .transport import Transport
from .stdio import StdioTransport
from .server import RPCServer

__all__ = [
    "RPCRequest",
    "RPCResponse",
    "RPCError",
    "Transport",
    "StdioTransport",
    "RPCServer",
]
