# tests/test_codeact.py

"""Tests for the standalone CodeAct worker and subprocess backend."""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from commamatrix.builtin.codeact.executor.backend import ExecutionResult
from commamatrix.builtin.codeact.executor.subproc import SubprocessBackend
from commamatrix.builtin.codeact.rpc.protocol import (
    Namespace,
    RPCError,
    RPCRequest,
    RPCResponse,
    ToolsMethod,
)
from commamatrix.builtin.codeact.rpc.tcp import TcpServer, TcpTransport

_WORKER_PATH = str(
    Path(__file__).resolve().parents[1]
    / "src/commamatrix/builtin/codeact/executor/worker.py"
)


class _FakeToolManager:
    def __init__(self, descriptor):
        self.descriptors = [descriptor]

    @staticmethod
    def build_tool_tree(descriptors):
        from commamatrix.components.tool import ToolManager

        return ToolManager.build_tool_tree(descriptors)

    def public_name(self, descriptor):
        if not descriptor.alias:
            return descriptor.name
        return f"{descriptor.alias}_{descriptor.name}"

    def resolve(self, name):
        return next((d for d in self.descriptors if self.public_name(d) == name), None)

    def resolve_id(self, id_str):
        return next((d for d in self.descriptors if d.id == id_str), None)


class _FakeServices:
    def __init__(self, runtime):
        self._runtime = runtime

    def require(self, _service_cls):
        return self._runtime


class _FakeRuntime:
    async def invoke_tool(self, ctx, tool_call):
        _, result = await ctx.run.agent._run_tool_lifecycle(ctx.run, tool_call)
        return result.content


class _FakeAgent:
    def __init__(self):
        descriptor = SimpleNamespace(
            id="python://test_tools/echo",
            namespace="test_tools",
            alias="test_tools",
            name="echo",
            doc="Echo a message.",
            schema={
                "type": "function",
                "parameters": {
                    "type": "object",
                    "properties": {"msg": {"type": "string"}},
                    "required": ["msg"],
                },
            },
            meta={"signature": [{"name": "msg", "kind": "KEYWORD_ONLY"}]},
        )
        self.calls = []
        self.tool_manager = _FakeToolManager(descriptor)
        self.services = _FakeServices(_FakeRuntime())

    async def _run_tool_lifecycle(self, run, tool_call):
        self.calls.append(tool_call)
        return None, SimpleNamespace(content=f"echo: {tool_call.tool_args['msg']}")


class _FakeProcess:
    def __init__(self):
        self.stderr = asyncio.StreamReader()
        self.returncode = None
        self.kill_called = False
        self.terminate_called = False

    def kill(self):
        self.kill_called = True
        self.returncode = -9

    def terminate(self):
        self.terminate_called = True

    async def wait(self):
        return self.returncode


def _backend_context():
    agent = _FakeAgent()
    return SimpleNamespace(run=SimpleNamespace(agent=agent)), agent


@asynccontextmanager
async def _worker(payload):
    loop = asyncio.get_running_loop()
    connection: asyncio.Future[TcpTransport] = loop.create_future()
    token = secrets.token_urlsafe(24)
    accept_errors: list[str] = []

    async def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            transport = await TcpTransport.accept(reader, writer, token, timeout=2)
        except Exception as exc:
            accept_errors.append(f"{type(exc).__name__}: {exc}")
            return
        if connection.done():
            await transport.close()
        else:
            connection.set_result(transport)

    server = await asyncio.start_server(accept, host="127.0.0.1", port=0)
    socket = server.sockets[0]
    host, port = socket.getsockname()[:2]
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
    transport: TcpTransport | None = None
    try:
        try:
            transport = await asyncio.wait_for(connection, timeout=5)
        except TimeoutError as exc:
            raise AssertionError(accept_errors) from exc
        await transport.send(payload)
        yield proc, transport
    finally:
        if transport is not None:
            await transport.close(timeout=2)
        server.close()
        await server.wait_closed()
        if proc.returncode is None:
            proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
                await asyncio.wait_for(proc.wait(), timeout=2)
        if proc.returncode is None:
            proc.kill()
            with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
                await asyncio.wait_for(proc.wait(), timeout=2)
        if proc.stderr is not None:
            with contextlib.suppress(Exception):
                await proc.stderr.read()


def _payload(code: str, tool_tree: dict | None = None) -> dict:
    return {
        "code": code,
        "namespace": {"__name__": "__codeact__"},
        "codeact_rpc_timeout": 2.0,
        "tool_tree": tool_tree or {},
    }


def _tool_tree() -> dict:
    return {
        "tools": {
            "test_tools": {
                "__tools__": [{
                    "id": "python://test_tools/echo",
                    "name": "echo",
                    "doc": "Echo a message.",
                    "schema": {
                        "type": "function",
                        "parameters": {
                            "type": "object",
                            "properties": {"msg": {"type": "string"}},
                            "required": ["msg"],
                        },
                    },
                    "meta": {"signature": [{"name": "msg", "kind": "KEYWORD_ONLY"}]},
                }],
            },
        },
    }


@pytest.mark.asyncio
async def test_tcp_server_authenticates_and_round_trips():
    server = TcpServer("secret", handshake_timeout=2)
    host, port = await server.start()
    client_task = asyncio.create_task(TcpTransport.connect(host, port, "secret", timeout=2))
    server_transport = await server.accept(timeout=2)
    client = await client_task

    try:
        await server_transport.send({"type": "ping"})
        assert await client.recv() == {"type": "ping"}
    finally:
        await client.close(timeout=0.2)
        await server_transport.close(timeout=0.2)
        await server.close(timeout=0.2)


@pytest.mark.asyncio
async def test_tcp_server_rejects_invalid_token():
    server = TcpServer("secret", handshake_timeout=0.2)
    host, port = await server.start()
    reader, writer = await asyncio.open_connection(host, port)
    writer.write(b'{"type":"hello","token":"wrong"}' + bytes([10]))
    await writer.drain()

    with pytest.raises(asyncio.TimeoutError):
        await server.accept(timeout=0.5)

    assert await reader.read() == b""
    writer.close()
    await writer.wait_closed()
    await server.close(timeout=0.2)


class TestExecutionResult:
    def test_console_output(self):
        result = ExecutionResult(stdout="out", stderr="err", returncode=1, duration_ms=1234.5)
        output = result.console_output()
        assert "out" in output
        assert "stderr:\nerr" in output
        assert "exit code: 1" in output
        assert "1234ms" in output

    def test_empty_console_output(self):
        assert ExecutionResult().console_output() == ""


class TestRPCProtocol:
    def test_request_defaults(self):
        request = RPCRequest(id="abc", method="tools.invoke")
        assert request.params == {}

    def test_response_result_and_error(self):
        response = RPCResponse(id="abc", result=42)
        assert response.error is None
        error = RPCError(code=-32601, message="not found")
        assert RPCResponse(id="abc", error=error).error is error

    def test_enums(self):
        assert Namespace.TOOLS == "tools"
        assert ToolsMethod.INVOKE == "invoke"


@pytest.mark.asyncio
async def test_worker_executes_code_over_tcp():
    async with _worker(_payload('print("hello")')) as (_, transport):
        response = await asyncio.wait_for(transport.recv(), timeout=5)

    assert response["type"] == "execution_result"
    assert response["result"]["stdout"] == "hello\n"
    assert response["result"]["returncode"] == 0


@pytest.mark.asyncio
async def test_worker_supports_top_level_await():
    code = 'import asyncio\nprint("before")\nawait asyncio.sleep(0.01)\nprint("after")'
    async with _worker(_payload(code)) as (_, transport):
        response = await asyncio.wait_for(transport.recv(), timeout=5)

    result = response["result"]
    assert result["stdout"] == "before\nafter\n"
    assert result["returncode"] == 0


@pytest.mark.asyncio
async def test_worker_returns_python_error():
    async with _worker(_payload('raise ValueError("broken")')) as (_, transport):
        response = await asyncio.wait_for(transport.recv(), timeout=5)

    result = response["result"]
    assert result["returncode"] == 1
    assert "ValueError: broken" in result["stderr"]


@pytest.mark.asyncio
async def test_worker_rpc_round_trip():
    code = 'from tools.test_tools import echo\nanswer = await echo(msg="hello")\nprint(answer)'
    async with _worker(_payload(code, _tool_tree())) as (_, transport):
        request = await asyncio.wait_for(transport.recv(), timeout=5)
        assert request["method"] == "tools.invoke"
        assert request["params"]["tool_id"] == "python://test_tools/echo"
        assert request["params"]["tool_args"] == {"msg": "hello"}
        await transport.send({"id": request["id"], "result": "echo: hello"})
        response = await asyncio.wait_for(transport.recv(), timeout=5)

    assert response["result"]["stdout"] == "echo: hello\n"
    assert response["result"]["returncode"] == 0


@pytest.mark.asyncio
async def test_subprocess_backend_executes_code():
    ctx, _ = _backend_context()
    result = await SubprocessBackend(execution_timeout=5).execute('print("hello")', ctx)

    assert result.returncode == 0
    assert result.stdout == "hello\n"
    assert result.stderr == ""
    assert result.duration_ms is not None


@pytest.mark.asyncio
async def test_subprocess_backend_invokes_nested_tool_over_tcp_rpc():
    ctx, agent = _backend_context()
    result = await SubprocessBackend(execution_timeout=5, rpc_timeout=2).execute(
        'from tools.test_tools import echo\nanswer = await echo(msg="hello")\nprint(answer)',
        ctx,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "echo: hello\n"
    assert len(agent.calls) == 1
    assert agent.calls[0].tool_name == "test_tools_echo"
    assert agent.calls[0].tool_args == {"msg": "hello"}


@pytest.mark.asyncio
async def test_subprocess_backend_returns_python_errors():
    ctx, _ = _backend_context()
    result = await SubprocessBackend(execution_timeout=5).execute('raise ValueError("broken")', ctx)

    assert result.returncode == 1
    assert "ValueError: broken" in result.stderr


@pytest.mark.asyncio
async def test_subprocess_backend_enforces_execution_timeout():
    ctx, _ = _backend_context()
    result = await SubprocessBackend(execution_timeout=0.5, shutdown_timeout=1).execute(
        "import asyncio\nawait asyncio.sleep(30)",
        ctx,
    )

    assert result.returncode == 124
    assert "Execution timed out" in result.stderr


@pytest.mark.asyncio
async def test_subprocess_backend_kills_worker_on_timeout(monkeypatch):
    process = _FakeProcess()

    async def create_process(*_args, **_kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    ctx, _ = _backend_context()
    result = await SubprocessBackend(execution_timeout=0.01, shutdown_timeout=0.01).execute(
        "await asyncio.sleep(30)",
        ctx,
    )

    assert result.returncode == 124
    assert process.kill_called
    assert not process.terminate_called


@pytest.mark.asyncio
async def test_subprocess_backend_kills_worker_on_cancellation(monkeypatch):
    process = _FakeProcess()
    process_created = asyncio.Event()

    async def create_process(*_args, **_kwargs):
        process_created.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    ctx, _ = _backend_context()
    backend = SubprocessBackend(execution_timeout=30, shutdown_timeout=0.01)
    task = asyncio.create_task(backend.execute("await asyncio.sleep(30)", ctx))
    await asyncio.wait_for(process_created.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)

    assert process.kill_called
    assert not process.terminate_called


@pytest.mark.asyncio
async def test_subprocess_backend_cancellation_cleans_up_worker():
    ctx, _ = _backend_context()
    backend = SubprocessBackend(execution_timeout=30, shutdown_timeout=1)
    task = asyncio.create_task(backend.execute("import asyncio\nawait asyncio.sleep(30)", ctx))
    await asyncio.sleep(0.1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=3)


def test_subprocess_backend_truncates_utf8_by_bytes():
    backend = SubprocessBackend(max_output_bytes=5)
    result = backend._truncate("я" * 10)
    prefix = result.removesuffix("\n...(output truncated)")

    assert result.endswith("\n...(output truncated)")
    assert len(prefix.encode("utf-8")) <= 5

