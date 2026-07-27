# tests/test_codeact_extras.py

"""Tests for CodeAct hooks, BM25ToolSearcher, RPCServer, and is_codeact_internal."""

from __future__ import annotations

import weakref
from types import SimpleNamespace

import pytest

from commamatrix.builtin.codeact.hooks import (
    codeact_enabled,
    expose_codeact_tools,
)
from commamatrix.builtin.codeact.search.bm25 import BM25ToolSearcher
from commamatrix.builtin.codeact.rpc.server import (
    RPCServer,
    is_codeact_internal,
    serialize_tool_descriptor,
)
from commamatrix.builtin.codeact.rpc.protocol import RPCError
from commamatrix.components.hook import BeforeLlmCallCtx
from commamatrix.components.tool import ToolDescriptor, PythonToolSource


def _make_desc(
    name: str,
    alias: str = "test",
    codeact: bool = False,
    namespace: str = "test",
) -> ToolDescriptor:
    src = PythonToolSource()
    return ToolDescriptor(
        id=f"python://{namespace}/{name}",
        namespace=namespace,
        alias=alias,
        name=name,
        doc=f"Tool {name}",
        schema={
            "type": "function",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
        meta={"codeact": False} if codeact else {} if codeact else {},
        _source_ref=weakref.ref(src),
    )


class TestIsCodeactInternal:
    def test_codeact_tool(self):
        d = _make_desc("exec", codeact=True)
        assert is_codeact_internal(d) is True

    def test_regular_tool(self):
        d = _make_desc("search")
        assert is_codeact_internal(d) is False

    def test_tool_opted_out_of_codeact(self):
        d = _make_desc("private")
        d.meta["codeact"] = False
        assert is_codeact_internal(d) is True


class TestBM25ToolSearcher:
    def test_empty_search(self):
        searcher = BM25ToolSearcher()
        assert searcher.search("test") == []

    def test_rebuild_and_search(self):
        src = PythonToolSource()
        d1 = ToolDescriptor(
            id="python://math/calculator",
            namespace="math",
            alias="math",
            name="calculator",
            doc="Evaluate a mathematical expression and return the result.",
            schema={
                "type": "function",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
            meta={},
            _source_ref=weakref.ref(src),
        )
        d2 = ToolDescriptor(
            id="python://web/web_search",
            namespace="web",
            alias="web",
            name="web_search",
            doc="Search the web for information about a query.",
            schema={
                "type": "function",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
            meta={},
            _source_ref=weakref.ref(src),
        )
        searcher = BM25ToolSearcher()
        searcher.rebuild_index("fp1", [d1, d2])
        results = searcher.search("evaluate mathematical expression")
        assert len(results) > 0
        assert results[0].name == "calculator"

    def test_rebuild_no_change(self):
        searcher = BM25ToolSearcher()
        d1 = _make_desc("a")
        searcher.rebuild_index("fp1", [d1])
        searcher.rebuild_index("fp1", [d1])
        assert len(searcher._ids) == 1

    def test_rebuild_empty_clears(self):
        searcher = BM25ToolSearcher()
        d1 = _make_desc("a")
        searcher.rebuild_index("fp1", [d1])
        searcher.rebuild_index("fp2", [])
        assert searcher.search("a") == []

    def test_aliases(self):
        searcher = BM25ToolSearcher()
        d1 = _make_desc("a", alias="mod1")
        d2 = _make_desc("b", alias="mod2")
        searcher.rebuild_index("fp", [d1, d2])
        aliases = searcher.aliases()
        assert set(aliases) == {"mod1", "mod2"}

    def test_tools_by_alias(self):
        searcher = BM25ToolSearcher()
        d1 = _make_desc("a", alias="mod1")
        d2 = _make_desc("b", alias="mod1")
        d3 = _make_desc("c", alias="mod2")
        searcher.rebuild_index("fp", [d1, d2, d3])
        assert len(searcher.tools("mod1")) == 2
        assert len(searcher.tools("mod2")) == 1
        assert len(searcher.tools("nonexistent")) == 0

    def test_descriptors_property(self):
        searcher = BM25ToolSearcher()
        d1 = _make_desc("a", alias="mod1")
        d2 = _make_desc("b", alias="mod2")
        searcher.rebuild_index("fp", [d1, d2])
        result = searcher.descriptors
        assert len(result) == 2
        assert {d.name for d in result} == {"a", "b"}

    def test_descriptors_property_empty(self):
        searcher = BM25ToolSearcher()
        assert searcher.descriptors == []


@pytest.mark.asyncio
async def test_codeact_hook_builds_index():
    descriptor = _make_desc("weather")
    searcher = BM25ToolSearcher()

    def get_config(field):
        return True if field is codeact_enabled else field.default

    runtime = SimpleNamespace(
        config=SimpleNamespace(get=get_config),
        searcher=searcher,
        backend=SimpleNamespace(environment_description=lambda: "test environment"),
        rebuild_index=lambda tools, run: searcher.rebuild_index("fp", tools),
    )
    services = SimpleNamespace(
        get=lambda service_cls: runtime,
        require=lambda service_cls: runtime,
    )
    agent = SimpleNamespace(
        services=services,
        tool_manager=SimpleNamespace(descriptors=[descriptor], fingerprint="fp"),
    )
    run = SimpleNamespace(agent=agent, chain_state={})
    before_llm = BeforeLlmCallCtx(run=run, dialog=[], tools=[descriptor])

    await expose_codeact_tools(before_llm)

    assert len(searcher.descriptors) == 1
    assert searcher.descriptors[0].name == "weather"


@pytest.mark.asyncio
async def test_codeact_exposes_only_control_tools():
    regular = _make_desc("weather")
    controls = []
    for name in (
        "execute",
        "search_tools",
        "list_tools",
    ):
        control = _make_desc(name, namespace="commamatrix.builtin.codeact.tools")
        control.meta.update({"codeact": False})
        controls.append(control)

    searcher = BM25ToolSearcher()
    runtime = SimpleNamespace(
        config=SimpleNamespace(get=lambda field: field.default),
        searcher=searcher,
        rebuild_index=lambda tools, run: searcher.rebuild_index("fp", tools),
    )
    agent = SimpleNamespace(
        services=SimpleNamespace(get=lambda service_cls: runtime),
        tool_manager=SimpleNamespace(
            descriptors=[regular, *controls], fingerprint="fp"
        ),
    )
    run = SimpleNamespace(agent=agent, chain_state={})
    ctx = BeforeLlmCallCtx(run=run, dialog=[], tools=[regular, *controls])

    await expose_codeact_tools(ctx)

    assert {descriptor.name for descriptor in ctx.tools} == {
        "execute",
        "search_tools",
        "list_tools",
    }


class TestSerializeToolDescriptor:
    def test_serialization(self):
        d = _make_desc("my_tool", alias="my_mod")
        result = serialize_tool_descriptor(d)
        assert result["id"] == "python://test/my_tool"
        assert result["name"] == "my_tool"
        assert result["alias"] == "my_mod"
        assert result["doc"] == "Tool my_tool"
