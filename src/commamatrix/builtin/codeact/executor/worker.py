# builtin/codeact/executor/worker.py

"""CodeAct worker — runs in a child Python process.

Connects to the parent over TCP, receives a JSON payload (code + namespace
+ tool_tree), sets up RPC-backed virtual imports for tool modules, executes
the code, and sends the execution result back over TCP.

The code is compiled with ``PyCF_ALLOW_TOP_LEVEL_AWAIT`` and evaluated
inside the worker event loop.  This is required because virtual tool
functions are asynchronous RPC proxies and must be awaited while the
worker continues processing RPC responses.
"""

import ast
import asyncio
import contextlib
import inspect
import io
import json
import struct
import sys
import time
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import Any, Callable
from uuid import uuid4


# ── Length-prefixed message helpers ─────────────────────────────────


def _write_msg(writer: asyncio.StreamWriter, data: bytes) -> None:
    header = struct.pack("!I", len(data))
    writer.write(header + data)


async def _read_msg(reader: asyncio.StreamReader) -> bytes:
    header = await reader.readexactly(4)
    length = struct.unpack("!I", header)[0]
    return await reader.readexactly(length)


# ── RPC client ───────────────────────────────────────────────────────


class AsyncRPCClient:
    def __init__(self, reader, writer, rpc_timeout: float = 10.0):
        self._reader = reader
        self._writer = writer
        self._rpc_timeout = rpc_timeout
        self._write_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future] = {}
        self._closed = False

    async def request(self, method, params=None):
        if self._closed:
            raise RuntimeError("RPC client is closed")
        request_id = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        payload = {"id": request_id, "method": method, "params": params or {}}
        async with self._write_lock:
            _write_msg(
                self._writer,
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )
            await self._writer.drain()
        try:
            return await asyncio.wait_for(future, timeout=self._rpc_timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(f"RPC timeout for {method}")
        finally:
            self._pending.pop(request_id, None)

    async def read_responses(self):
        try:
            while not self._closed:
                data = await _read_msg(self._reader)
                response = json.loads(data.decode("utf-8"))
                rid = response.get("id")
                if rid in self._pending:
                    future = self._pending.pop(rid)
                    if future.done():
                        continue
                    if response.get("error"):
                        error = response["error"]
                        future.set_exception(
                            RuntimeError(
                                f"RPC error {error['code']}: {error['message']}"
                            )
                        )
                    else:
                        future.set_result(response.get("result"))
        except (ConnectionError, EOFError):
            pass
        except asyncio.IncompleteReadError:
            pass
        finally:
            self._closed = True
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("RPC connection closed"))

    async def close(self):
        self._closed = True
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RuntimeError("RPC client closed"))


# ── Schema / signature helpers ───────────────────────────────────────


def _schema_type(schema):
    if not isinstance(schema, dict):
        return Any
    if "anyOf" in schema:
        types = [
            _schema_type(item) for item in schema["anyOf"] if item.get("type") != "null"
        ]
        return types[0] if len(types) == 1 else Any
    return {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }.get(schema.get("type"), Any)


def _signature(schema, metadata=None):
    schema = schema.get("parameters", schema) if isinstance(schema, dict) else {}
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    required = set(schema.get("required", [])) if isinstance(schema, dict) else set()
    metadata = metadata if isinstance(metadata, dict) else {}
    declared = metadata.get("signature", [])
    parameters = []
    annotations = {}
    for item in declared if isinstance(declared, list) else []:
        name = item.get("name")
        if not isinstance(name, str) or name not in properties:
            continue
        kind = getattr(
            inspect.Parameter,
            item.get("kind", "KEYWORD_ONLY"),
            inspect.Parameter.KEYWORD_ONLY,
        )
        has_default = "default" in item or "default" in properties[name]
        default = (
            inspect.Parameter.empty
            if name in required and not has_default
            else item.get("default", properties[name].get("default", None))
        )
        parameter = inspect.Parameter(
            name, kind, default=default, annotation=_schema_type(properties[name])
        )
        parameters.append(parameter)
        annotations[name] = parameter.annotation
    if not parameters:
        for name, definition in properties.items():
            default = (
                inspect.Parameter.empty
                if name in required
                else definition.get("default", None)
            )
            parameter = inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=_schema_type(definition),
            )
            parameters.append(parameter)
            annotations[name] = parameter.annotation
    return inspect.Signature(parameters), annotations


def _make_tool_proxy(client, descriptor):
    signature, annotations = _signature(
        descriptor.get("schema", {}), descriptor.get("meta", {})
    )
    tool_id = descriptor["id"]
    proxy_name = descriptor["name"]

    async def proxy(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        return await client.request(
            "tools.invoke",
            {
                "tool_id": tool_id,
                "tool_args": dict(bound.arguments),
                "tool_call_id": "",
            },
        )

    proxy.__name__ = proxy_name
    proxy.__doc__ = descriptor.get("doc", "")
    proxy.__signature__ = signature
    proxy.__annotations__ = annotations
    return proxy


def _make_ambiguous_proxy(name, descriptors):
    async def proxy(*args, **kwargs):
        candidates = [
            f"{d.get('id', '?')} (name={d.get('name', '?')})" for d in descriptors
        ]
        raise RuntimeError(
            f"Tool {name!r} is ambiguous — Candidates: " + "; ".join(candidates)
        )

    proxy.__name__ = name
    proxy.__doc__ = f"AMBIGUOUS: {name!r}"
    return proxy


# ── Virtual module factories ─────────────────────────────────────────

_modules_cache: dict[str, ModuleType] = {}
_factories: dict[str, Callable[..., Any]] = {}


class _ToolModule(ModuleType):
    def __init__(self, fullname: str, call_proxy: Callable[..., Any] | None = None) -> None:
        super().__init__(fullname)
        self.__call_proxy = call_proxy
        if call_proxy is not None:
            self.__doc__ = call_proxy.__doc__
            signature = getattr(call_proxy, "__signature__", None)
            if signature is not None:
                self.__signature__ = signature

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self.__call_proxy is None:
            raise TypeError(f"Module {self.__name__!r} is not a callable tool")
        return self.__call_proxy(*args, **kwargs)


def make_tool_module(fullname, node, client):
    descriptors = node.get("__tools__", [])
    if len(descriptors) == 1:
        call_proxy = _make_tool_proxy(client, descriptors[0])
    elif descriptors:
        call_proxy = _make_ambiguous_proxy(fullname, descriptors)
    else:
        call_proxy = None

    module = _ToolModule(fullname, call_proxy)
    module.__path__ = []
    module.__package__ = fullname
    _modules_cache[fullname] = module
    by_name: dict[str, list[dict[str, Any]]] = {}
    for descriptor in node.get("__tools__", []):
        by_name.setdefault(descriptor["name"], []).append(descriptor)
    names = []
    for name, descriptors in by_name.items():
        if len(descriptors) > 1:
            proxy = _make_ambiguous_proxy(name, descriptors)
        else:
            proxy = _make_tool_proxy(client, descriptors[0])
        setattr(module, name, proxy)
        names.append(name)
    for child_name, child_node in node.items():
        if child_name == "__tools__":
            continue
        child_fullname = f"{fullname}.{child_name}"
        if child_fullname not in _factories:
            _factories[child_fullname] = lambda cn=child_fullname, nd=child_node: (
                make_tool_module(cn, nd, client)
            )
        setattr(module, child_name, _factories[child_fullname]())
        names.append(child_name)
    module.__all__ = names
    return module


class _Finder(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in _factories:
            return None
        return ModuleSpec(fullname, _Loader(fullname))


class _Loader:
    def __init__(self, fullname):
        self._fullname = fullname

    def create_module(self, spec):
        if self._fullname in _modules_cache:
            return _modules_cache[self._fullname]
        return _factories[self._fullname]()

    def exec_module(self, module):
        pass


# ── Entry point ──────────────────────────────────────────────────────


async def _send_message(writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
    _write_msg(writer, json.dumps(message, ensure_ascii=False).encode("utf-8"))
    await writer.drain()


async def main(host: str, port: int, token: str) -> None:
    reader, writer = await asyncio.open_connection(host, port)
    await _send_message(writer, {"type": "hello", "token": token})

    handshake_data = await _read_msg(reader)
    if json.loads(handshake_data.decode("utf-8")).get("type") != "hello_ok":
        raise PermissionError("CodeAct TCP handshake rejected")

    boot_data = await _read_msg(reader)
    payload = json.loads(boot_data.decode("utf-8"))
    code = payload["code"]
    namespace = payload.get("namespace") or {"__name__": "__codeact__"}
    tool_tree = payload.get("tool_tree") or {}
    rpc_timeout = payload.get("rpc_timeout", 10.0)

    client = AsyncRPCClient(reader, writer, rpc_timeout=rpc_timeout)
    reader_task = asyncio.create_task(client.read_responses())

    _modules_cache.clear()
    _factories.clear()
    tools_node = tool_tree.get("tools", {})
    for alias, node in tools_node.items():
        _factories[f"tools.{alias}"] = lambda a=f"tools.{alias}", n=node: (
            make_tool_module(a, n, client)
        )

    tools_mod = ModuleType("tools")
    tools_mod.__path__ = []
    tools_mod.__package__ = "tools"
    tools_mod.__all__ = list(tools_node.keys())
    _modules_cache["tools"] = tools_mod
    _factories["tools"] = lambda: tools_mod
    sys.meta_path.insert(0, _Finder())

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    returncode = 0
    elapsed = 0.0
    try:
        start = time.monotonic()
        with (
            contextlib.redirect_stdout(stdout_buf),
            contextlib.redirect_stderr(stderr_buf),
        ):
            compiled = compile(
                code,
                "<codeact>",
                "exec",
                flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
            )

            result = eval(compiled, namespace)
            if inspect.isawaitable(result):
                await result
        elapsed = (time.monotonic() - start) * 1000
    except BaseException as exc:
        stderr_buf.write(f"{type(exc).__name__}: {exc}")
        returncode = 1

    reader_task.cancel()
    try:
        await reader_task
    except asyncio.CancelledError:
        pass
    await client.close()

    response = {
        "type": "execution_result",
        "id": "",
        "result": {
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "returncode": returncode,
            "elapsed": elapsed,
        },
    }
    await _send_message(writer, response)
    writer.close()
    await writer.wait_closed()


if __name__ == "__main__":
    if (
        len(sys.argv) != 7
        or sys.argv[1] != "--host"
        or sys.argv[3] != "--port"
        or sys.argv[5] != "--token"
    ):
        raise SystemExit("usage: worker.py --host HOST --port PORT --token TOKEN")
    asyncio.run(main(sys.argv[2], int(sys.argv[4]), sys.argv[6]))
