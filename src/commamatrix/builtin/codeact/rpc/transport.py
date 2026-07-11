# builtin/codeact/rpc/transport.py

"""Abstract bidirectional transport for RPC messages."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Transport(ABC):
    """Send and receive JSON-serialisable message dicts over a byte stream."""

    @abstractmethod
    async def send(self, message: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def recv(self) -> dict[str, Any]:
        raise NotImplementedError

    async def close(self) -> None:
        pass
