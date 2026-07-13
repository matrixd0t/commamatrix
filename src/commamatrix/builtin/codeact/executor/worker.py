# builtin/codeact/executor/worker.py

"""CodeAct worker — runs in a child Python process.

Reads a JSON payload from stdin (code + namespace), sets up RPC-backed
virtual imports (``context``, tool modules), executes the code, and
writes the execution result (stdout, stderr, returncode, elapsed) back
to stdout as JSON.
"""

import ast
import asyncio
import contextlib
import inspect
import io
import json
import os
import sys
import threading
import time
import uuid
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import Any


# ── I/O setup ────────────────────────────────────────────────────────

stdin_bin = os.fdopen(0, "rb", 0)
stdout_bin = os.fdopen(1, "wb", 0)


# ── RPC client ───────────────────────────────────────────────────────

class _RPCClient:
    def __init__(self, reader, writer):
        self._reader = reader
        self._writer = writer
        self._lock = threading.Lock()

    def call(self, method, params=None):
        request = {"id": uuid.uuid4().hex, "method": method, "params": params or {}}
        with self._lock:
            self._writer.write(json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n")
            self._writer.flush()
            response = json.loads(self._reader.readline())
        if response.get("error"):
            error = response["error"]
            raise RuntimeError(f"RPC error {error['code']}: {error['message']}")
        return response.get("result")

    async def acall(self, method, params=None):
        return await asyncio.to_thread(self.call, method, params)


# ── Remote proxy objects ─────────────────────────────────────────────

class _RemoteCall:
    def __init__(self, client, path, args, kwargs):
        self._client = client
        self._path = path
        self._args = args
        self._kwargs = kwargs

    def __await__(self):
        params = {"args": list(self._args), "kwargs": self._kwargs}
        return self._client.acall(self._path, params).__await__()


class _RemoteValue:
    def __init__(self, client, path):
        self._client = client
        self._path = path

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return _RemoteValue(self._client, self._path + "." + name)

    def __call__(self, *args, **kwargs):
        return _RemoteCall(self._client, self._path, args, kwargs)

    def __await__(self):
        return self._client.acall(self._path).__await__()

    def __repr__(self):
        return f"<RemoteValue {self._path}>"


class _ToolsAccessor:
    def __init__(self, client):
        self._client = client

    async def invoke(self, tool_name, args=None):
        return await self._client.acall("tools.invoke", {"tool_call": {
            "tool_call_id": "", "tool_name": tool_name, "tool_args": args or {},
        }})

    async def search(self, query, limit=5):
        return await self._client.acall("tools.search", {"query": query, "limit": limit})

    def __repr__(self):
        return "<ToolsAccessor>"


# ── Schema / signature helpers ───────────────────────────────────────

def _schema_type(schema):
    if not isinstance(schema, dict):
        return Any
    if "anyOf" in schema:
        types = [_schema_type(item) for item in schema["anyOf"] if item.get("type") != "null"]
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
        kind = getattr(inspect.Parameter, item.get("kind", "KEYWORD_ONLY"), inspect.Parameter.KEYWORD_ONLY)
        has_default = "default" in item or "default" in properties[name]
        default = inspect.Parameter.empty if name in required and not has_default else item.get("default", properties[name].get("default", None))
        parameter = inspect.Parameter(
            name, kind, default=default, annotation=_schema_type(properties[name]),
        )
        parameters.append(parameter)
        annotations[name] = parameter.annotation
    if not parameters:
        for name, definition in properties.items():
            default = inspect.Parameter.empty if name in required else definition.get("default", None)
            parameter = inspect.Parameter(
                name, inspect.Parameter.KEYWORD_ONLY,
                default=default, annotation=_schema_type(definition),
            )
            parameters.append(parameter)
            annotations[name] = parameter.annotation
    return inspect.Signature(parameters), annotations


def _make_tool_proxy(client, descriptor):
    signature, annotations = _signature(descriptor.get("schema", {}), descriptor.get("metadata", {}))
    name = descriptor["name"]

    async def proxy(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        return await client.acall("tools.invoke", {"tool_call": {
            "tool_call_id": "", "tool_name": name, "tool_args": dict(bound.arguments),
        }})

    proxy.__name__ = name
    proxy.__doc__ = descriptor.get("doc", "")
    proxy.__signature__ = signature
    proxy.__annotations__ = annotations
    return proxy


# ── Virtual module factories ─────────────────────────────────────────

def make_context(client):
    module = ModuleType("context")
    module.run = _RemoteValue(client, "context.run")
    module.tool_call = _RemoteValue(client, "context.tool_call")
    module.storage = _RemoteValue(client, "context.storage")
    module.meta = _RemoteValue(client, "context.meta")
    module.tools = _ToolsAccessor(client)
    module.__all__ = ["run", "tool_call", "storage", "meta", "tools"]
    return module


def make_tool_module(alias, client):
    module = ModuleType(alias)
    descriptors = client.call("tools.list", {"alias": alias}) or []
    names = []
    for descriptor in descriptors:
        name = descriptor["name"]
        setattr(module, name, _make_tool_proxy(client, descriptor))
        names.append(name)
    module.__all__ = names
    return module


# ── Virtual import machinery ─────────────────────────────────────────

class _Finder(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if "." in fullname or fullname not in modules:
            return None
        return ModuleSpec(fullname, _Loader(modules[fullname]))


class _Loader:
    def __init__(self, factory):
        self._factory = factory

    def create_module(self, spec):
        return self._factory()

    def exec_module(self, module):
        pass


# ── Entry point ──────────────────────────────────────────────────────

def main():
    payload = json.loads(stdin_bin.readline())
    code = payload["code"]
    namespace = payload.get("namespace") or {"__name__": "__codeact__"}

    client = _RPCClient(stdin_bin, stdout_bin)

    modules = {"context": lambda: make_context(client)}
    for alias in client.call("tools.aliases", {}) or []:
        modules[alias] = lambda a=alias: make_tool_module(a, client)
    sys.meta_path.insert(0, _Finder())

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    returncode = 0
    elapsed = 0.0
    try:
        start = time.monotonic()
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            compiled = compile(code, "<codeact>", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            result = eval(compiled, namespace)
            if result is not None:
                asyncio.run(result)
        elapsed = (time.monotonic() - start) * 1000
    except BaseException as exc:
        stderr_buf.write(f"{type(exc).__name__}: {exc}")
        returncode = 1

    response = {"id": "", "result": {
        "stdout": stdout_buf.getvalue(), "stderr": stderr_buf.getvalue(),
        "returncode": returncode, "elapsed": elapsed,
    }}
    stdout_bin.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
    stdout_bin.flush()


if __name__ == "__main__":
    main()
