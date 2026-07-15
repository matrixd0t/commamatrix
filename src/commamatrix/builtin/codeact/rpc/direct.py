# builtin/codeact/rpc/direct.py

from __future__ import annotations

import asyncio
from typing import Any

from .transport import Transport


class DirectTransport(Transport):
    def __init__(self) -> None:
        self._inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._outbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def send(self, message: dict[str, Any]) -> None:
        await self._outbox.put(message)

    async def recv(self) -> dict[str, Any]:
        return await self._inbox.get()

    def feed(self, message: dict[str, Any]) -> None:
        self._inbox.put_nowait(message)

    async def drain(self) -> dict[str, Any]:
        return await self._outbox.get()
