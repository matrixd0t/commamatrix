# tests/test_rpc_server.py

"""Tests for RPCServer dispatch and error handling."""

from __future__ import annotations

import weakref
from types import SimpleNamespace

import pytest

from commamatrix.builtin.codeact.rpc.server import RPCServer
from commamatrix.components.tool import PythonToolSource, ToolDescriptor, ToolManager
from commamatrix.core.classes.manager import ServiceInstanceRegistry


def _make_desc(name: str, alias: str = "test") -> ToolDescriptor:
    src = PythonToolSource()
    return ToolDescriptor(
        id=f"python://test/{name}",
        namespace="test",
        alias=alias,
        name=name,
        doc=f"Tool {name}",
        schema={
            "type": "function",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
        meta={},
        _source_ref=weakref.ref(src),
    )


def _make_ctx(tools=None):
    descriptors = tools or [_make_desc("echo")]
    src = PythonToolSource()
    for d in descriptors:
        src._functions[d.id] = lambda **kw: "result"

    agent = SimpleNamespace(
        tool_manager=SimpleNamespace(
            descriptors=descriptors,
            resolve_id=lambda id_str: next(
                (d for d in descriptors if d.id == id_str), None
            ),
            resolve=lambda name: next(
                (d for d in descriptors if f"{d.alias}_{d.name}" == name), None
            ),
            public_name=lambda d: f"{d.alias}_{d.name}" if d.alias else d.name,
            build_tool_tree=ToolManager.build_tool_tree,
            modules={d.alias: [d] for d in descriptors if d.alias},
            find_alias=lambda a: [d for d in descriptors if d.alias == a],
        ),
        services=ServiceInstanceRegistry(),
    )
    run = SimpleNamespace(agent=agent, origin=SimpleNamespace(), user="u")
    return SimpleNamespace(run=run)


class TestRPCServerDispatch:
    @pytest.mark.asyncio
    async def test_unknown_namespace(self):
        ctx = _make_ctx()
        server = RPCServer(ctx)
        resp = await server.handle({"id": "1", "method": "unknown.method"})
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_empty_method(self):
        ctx = _make_ctx()
        server = RPCServer(ctx)
        resp = await server.handle({"id": "1", "method": ""})
        assert "error" in resp

    @pytest.mark.asyncio
    async def test_tools_resolve(self):
        ctx = _make_ctx()
        server = RPCServer(ctx)
        resp = await server.handle(
            {"id": "1", "method": "tools.resolve", "params": {"name": "test_echo"}}
        )
        assert "result" in resp
        assert resp["result"]["name"] == "echo"

    @pytest.mark.asyncio
    async def test_tools_resolve_not_found(self):
        ctx = _make_ctx()
        server = RPCServer(ctx)
        resp = await server.handle(
            {"id": "1", "method": "tools.resolve", "params": {"name": "nonexistent"}}
        )
        assert resp["result"] is None

    @pytest.mark.asyncio
    async def test_unknown_tools_method(self):
        ctx = _make_ctx()
        server = RPCServer(ctx)
        resp = await server.handle({"id": "1", "method": "tools.nonexistent"})
        assert "error" in resp
