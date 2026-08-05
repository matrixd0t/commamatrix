# builtin/codeact/executor/subproc.py

"""Subprocess execution backend using an authenticated loopback TCP channel."""

from __future__ import annotations

import asyncio
import secrets
import sys
from pathlib import Path
from typing import Any

from .backend import ExecutionBackend, ExecutionResult
from ..rpc.server import is_codeact_internal
from ..rpc.server import RPCServer
from ..rpc.tcp import TcpServer, TcpTransport
from ....components.hook import BeforeToolCallCtx

_WORKER_PATH = str(Path(__file__).parent / "worker.py")


class SubprocessBackend(ExecutionBackend):
    """Run code in a separate process without security isolation."""

    def __init__(
        self,
        execution_timeout: float = 30.0,
        shutdown_timeout: float = 5.0,
        max_output_bytes: int = 1_000_000,
        rpc_timeout: float = 10.0,
    ) -> None:
        self._execution_timeout = execution_timeout
        self._shutdown_timeout = shutdown_timeout
        self._max_output_bytes = max_output_bytes
        self._rpc_timeout = rpc_timeout

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def environment_description(self) -> str:
        v = sys.version_info
        return (
            f"Python {v.major}.{v.minor}.{v.micro}. "
            "Full filesystem and network access — no security isolation. "
            "All standard library modules are available. "
            "Each execution starts with a clean namespace; no state persists between runs."
        )

    async def execute(self, code: str, ctx: BeforeToolCallCtx) -> ExecutionResult:
        server = RPCServer(ctx)
        tm = ctx.run.agent.tool_manager
        public_descriptors = [d for d in tm.descriptors if not is_codeact_internal(d)]
        payload = {
            "code": code,
            "namespace": {"__name__": "__codeact__"},
            "timeout": self._execution_timeout,
            "rpc_timeout": self._rpc_timeout,
            "tool_tree": tm.build_tool_tree(public_descriptors),
        }

        token = secrets.token_urlsafe(32)
        tcp_server: TcpServer | None = None
        proc: asyncio.subprocess.Process | None = None
        transport: TcpTransport | None = None
        stderr_reader: asyncio.Task | None = None
        rpc_tasks: list[asyncio.Task] = []
        response_data: dict[str, Any] | None = None
        stderr_buffer: list[str] = []
        is_timeout = False
        cancel_error: BaseException | None = None
        other_error: Exception | None = None

        try:
            tcp_server = TcpServer(token, handshake_timeout=self._rpc_timeout)
            host, port = await tcp_server.start()

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                _WORKER_PATH,
                "--host",
                str(host),
                "--port",
                str(port),
                "--token",
                token,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            assert proc.stderr is not None
            stderr_reader = asyncio.create_task(
                self._read_stderr(proc.stderr, stderr_buffer)
            )

            async with asyncio.timeout(self._execution_timeout):
                assert tcp_server is not None
                transport = await tcp_server.accept()
                assert transport is not None
                await transport.send(payload)

                while True:
                    message = await transport.recv()
                    if message.get("type") == "execution_result":
                        response_data = message
                        break
                    if "method" in message:
                        task = asyncio.create_task(
                            self._handle_rpc(server, transport, message)
                        )
                        rpc_tasks.append(task)
                        continue
                    stderr_buffer.append(f"Unknown worker message: {message!r}")
                    break

        except asyncio.TimeoutError:
            is_timeout = True
            stderr_buffer.append("Execution timed out")
        except asyncio.CancelledError as exc:
            cancel_error = exc
            stderr_buffer.append("Execution cancelled")
        except ConnectionError:
            stderr_buffer.append("Worker process connection lost")
        except Exception as exc:
            other_error = exc
            stderr_buffer.append(f"Execution error: {exc}")
        finally:
            if tcp_server is not None:
                await tcp_server.close(timeout=min(self._shutdown_timeout, 0.5))
            await self._cleanup(proc, transport, stderr_reader, rpc_tasks)

        stderr_text = "\n".join(stderr_buffer)
        if is_timeout:
            result = ExecutionResult(
                stderr=self._truncate(stderr_text),
                returncode=124,
                duration_ms=self._execution_timeout * 1000,
            )
        elif response_data is not None and isinstance(
            response_data.get("result"), dict
        ):
            worker_result = response_data["result"]
            worker_stderr = worker_result.get("stderr", "")
            combined_stderr = "\n".join(
                part for part in (stderr_text, worker_stderr) if part
            )
            result = ExecutionResult(
                stdout=self._truncate(worker_result.get("stdout", "")),
                stderr=self._truncate(combined_stderr),
                returncode=worker_result.get("returncode", 0),
                duration_ms=worker_result.get("elapsed"),
            )
        else:
            result = ExecutionResult(
                stderr=self._truncate(stderr_text or "Child process crashed"),
                returncode=1,
            )

        if cancel_error is not None:
            raise cancel_error
        if other_error is not None:
            raise other_error
        return result

    async def _handle_rpc(
        self, server: RPCServer, transport: TcpTransport, message: dict[str, Any]
    ) -> None:
        try:
            async with asyncio.timeout(self._rpc_timeout):
                rpc_response = await server.handle(message)
        except asyncio.TimeoutError:
            rpc_response = {
                "id": message.get("id", ""),
                "error": {"code": -32000, "message": "RPC timeout"},
            }
        try:
            await transport.send(rpc_response)
        except (ConnectionError, OSError):
            pass

    async def _read_stderr(self, stderr: asyncio.StreamReader, buffer: list[str]) -> None:
        try:
            while True:
                line = await stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                current_size = len("\n".join(buffer).encode("utf-8"))
                if current_size + len(text.encode("utf-8")) > self._max_output_bytes:
                    buffer.append("...(stderr truncated)")
                    break
                buffer.append(text.rstrip("\n"))
        except (ConnectionError, ValueError):
            pass

    def _truncate(self, text: str) -> str:
        encoded = text.encode("utf-8")
        if len(encoded) > self._max_output_bytes:
            truncated = encoded[: self._max_output_bytes].decode(
                "utf-8", errors="ignore"
            )
            return truncated + "\n...(output truncated)"
        return text

    async def _cleanup(
        self,
        proc: asyncio.subprocess.Process | None,
        transport: TcpTransport | None,
        stderr_reader: asyncio.Task | None,
        rpc_tasks: list[asyncio.Task],
    ) -> None:
        for task in rpc_tasks:
            if not task.done():
                task.cancel()
        if rpc_tasks:
            await asyncio.gather(*rpc_tasks, return_exceptions=True)

        if transport is not None:
            await transport.close(timeout=min(self._shutdown_timeout, 0.5))

        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=self._shutdown_timeout)
            except ProcessLookupError:
                pass
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), timeout=self._shutdown_timeout)
                except (ProcessLookupError, asyncio.TimeoutError):
                    pass

        if stderr_reader is not None:
            try:
                await asyncio.wait_for(stderr_reader, timeout=self._shutdown_timeout)
            except asyncio.TimeoutError:
                stderr_reader.cancel()
                await asyncio.gather(stderr_reader, return_exceptions=True)
            except asyncio.CancelledError:
                pass
