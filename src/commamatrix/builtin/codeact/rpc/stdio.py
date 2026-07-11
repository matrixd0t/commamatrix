# builtin/codeact/rpc/stdio.py

from __future__ import annotations

import asyncio
import json
from typing import Any

from .transport import Transport


class StdioTransport(Transport):
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process

    async def send(self, message: dict[str, Any]) -> None:
        data = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        assert self._process.stdin is not None
        self._process.stdin.write(data)
        await self._process.stdin.drain()

    async def recv(self) -> dict[str, Any]:
        assert self._process.stdout is not None
        line = await self._process.stdout.readline()
        if not line:
            raise ConnectionError("Process stdout closed")
        return json.loads(line.decode("utf-8"))

    async def close(self) -> None:
        if self._process.stdin and not self._process.stdin.is_closing():
            self._process.stdin.close()
        try:
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except (ProcessLookupError, asyncio.TimeoutError):
            self._process.kill()
