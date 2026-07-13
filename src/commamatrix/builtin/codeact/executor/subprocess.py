# builtin/codeact/executor/subprocess.py

"""Subprocess execution backend — runs code in a child Python process.

The child communicates with the parent over JSON-RPC on stdin/stdout,
allowing it to call back into the agent's tool runtime.
Intentionally NOT SECURE sandbox.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from .backend import ExecutionBackend, ExecutionResult
from ..rpc.server import RPCServer
from ..rpc.stdio import StdioTransport
from ....api.hooks import BeforeToolCallCtx

_WORKER_PATH = str(Path(__file__).parent / "worker.py")


class SubprocessBackend(ExecutionBackend):
    """Run code in a separate process WITHOUT security isolation."""

    def __init__(self, timeout: float | None = None) -> None:
        self._timeout = timeout or 30.0

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def execute(self, code: str, ctx: BeforeToolCallCtx, namespace: dict[str, Any] | None = None) -> ExecutionResult:
        server = RPCServer(ctx)
        payload = {
            "code": code,
            "namespace": namespace or {"__name__": "__codeact__"},
            "timeout": self._timeout,
        }

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            _WORKER_PATH,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        assert (
            proc.stdin is not None
            and proc.stdout is not None
            and proc.stderr is not None
        )
        transport = StdioTransport(proc)
        stderr_stream = proc.stderr
        await transport.send(payload)

        async def run_server() -> tuple[dict[str, Any] | None, str, int]:
            response_data = None
            try:
                while True:
                    message = await transport.recv()
                    if "method" in message:
                        rpc_response = await server.handle(message)
                        await transport.send(rpc_response)
                    elif "result" in message or "error" in message:
                        response_data = message
                        break
            except ConnectionError:
                pass
            await transport.close()
            stderr = await stderr_stream.read()
            await proc.wait()
            return response_data, stderr.decode("utf-8"), proc.returncode or 0

        try:
            response, stderr_text, returncode = await asyncio.wait_for(
                run_server(),
                timeout=self._timeout + 5.0,
            )
        except asyncio.TimeoutError:
            await transport.close()
            await proc.wait()
            return ExecutionResult(
                stderr="Execution timed out",
                returncode=124,
                duration_ms=self._timeout * 1000,
            )

        if response and "result" in response:
            result = response["result"]
            return ExecutionResult(
                stdout=result.get("stdout", ""),
                stderr=stderr_text + result.get("stderr", ""),
                returncode=result.get("returncode", returncode),
                duration_ms=result.get("elapsed"),
            )

        return ExecutionResult(
            stderr=stderr_text or "Child process crashed", returncode=returncode or 1
        )
