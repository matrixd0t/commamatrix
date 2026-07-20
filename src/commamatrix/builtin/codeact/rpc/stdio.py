# builtin/codeact/rpc/stdio.py

"""Stdio transport — newline-delimited JSON over asyncio subprocess pipes."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .transport import Transport


class StdioTransport(Transport):
    """Reads/writes newline-delimited JSON on a subprocess stdin/stdout.

    Safe to call ``close()`` even if the process terminated between
    construction and close — the implementation handles both
    ``ProcessLookupError`` and already-closed pipes gracefully.
    """

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process
        self._write_lock = asyncio.Lock()

    async def send(self, message: dict[str, Any]) -> None:
        data = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        assert self._process.stdin is not None
        async with self._write_lock:
            self._process.stdin.write(data)
            await self._process.stdin.drain()

    async def recv(self) -> dict[str, Any]:
        assert self._process.stdout is not None
        line = await self._process.stdout.readline()
        if not line:
            raise ConnectionError("Process stdout closed")
        return json.loads(line.decode("utf-8"))

    async def close(self, timeout: float = 5.0) -> None:
        try:
            if self._process.stdin and not self._process.stdin.is_closing():
                self._process.stdin.close()
        except (BrokenPipeError, ValueError):
            pass

        try:
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
        except ProcessLookupError:
            pass
        except asyncio.TimeoutError:
            try:
                self._process.kill()
                await asyncio.wait_for(self._process.wait(), timeout=timeout)
            except (ProcessLookupError, asyncio.TimeoutError):
                pass
