# tests/test_codeact_extras.py

"""Tests for CodeAct hooks, BM25ToolSearcher, RPCServer, and is_codeact_internal."""

from __future__ import annotations

import weakref
from types import SimpleNamespace

import pytest

from commamatrix.builtin.codeact import is_codeact_internal
from commamatrix.builtin.codeact.hooks import CODEACT_ENABLED_KEY, mark_codeact_enabled, expose_codeact_tools
from commamatrix.builtin.codeact.search.bm25 import BM25ToolSearcher
from commamatrix.builtin.codeact.rpc.server import RPCServer, serialize_tool_descriptor
from commamatrix.builtin.codeact.rpc.protocol import RPCError
from commamatrix.components.tool import ToolDescriptor, PythonToolSource
from commamatrix.core.classes.manager import ServiceInstanceRegistry

def _make_desc(name: str, alias: str = "test", codeact: bool = False) -> ToolDescriptor:
    src = PythonToolSource()
    return ToolDescriptor(
        id=f"python://test/{name}",
        namespace="test",
        alias=alias,
        name=name,
        doc=f"Tool {name}",
        schema={"type": "function", "parameters": {"type": "object", "properties": {}, "required": []}},
        meta={"codeact": True} if codeact else {},
        _source_ref=weakref.ref(src),
    )


class TestIsCodeactInternal:
    def test_codeact_tool(self):
        d = _make_desc("exec", codeact=True)
        assert is_codeact_internal(d) is True

    def test_regular_tool(self):
        d = _make_desc("search")
        assert is_codeact_internal(d) is False


class TestBM25ToolSearcher:
    def test_empty_search(self):
        searcher = BM25ToolSearcher()
        assert searcher.search("test") == []

    def test_rebuild_and_search(self):
        src = PythonToolSource()
        d1 = ToolDescriptor(
            id="python://math/calculator", namespace="math", alias="math",
            name="calculator", doc="Evaluate a mathematical expression and return the result.",
            schema={"type": "function", "parameters": {"type": "object", "properties": {}, "required": []}},
            meta={}, _source_ref=weakref.ref(src),
        )
        d2 = ToolDescriptor(
            id="python://web/web_search", namespace="web", alias="web",
            name="web_search", doc="Search the web for information about a query.",
            schema={"type": "function", "parameters": {"type": "object", "properties": {}, "required": []}},
            meta={}, _source_ref=weakref.ref(src),
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


class TestMarkCodeactEnabled:
    def test_sets_flag_when_service_missing(self):
        agent = SimpleNamespace(services=ServiceInstanceRegistry())
        run = SimpleNamespace(agent=agent, state={})
        ctx = SimpleNamespace(run=run)
        mark_codeact_enabled(ctx)
        assert ctx.run.state[CODEACT_ENABLED_KEY] is True

    def test_does_not_override_existing(self):
        agent = SimpleNamespace(services=ServiceInstanceRegistry())
        run = SimpleNamespace(agent=agent, state={CODEACT_ENABLED_KEY: False})
        ctx = SimpleNamespace(run=run)
        mark_codeact_enabled(ctx)
        assert ctx.run.state[CODEACT_ENABLED_KEY] is False


class TestSerializeToolDescriptor:
    def test_serialization(self):
        d = _make_desc("my_tool", alias="my_mod")
        result = serialize_tool_descriptor(d)
        assert result["id"] == "python://test/my_tool"
        assert result["name"] == "my_tool"
        assert result["alias"] == "my_mod"
        assert result["doc"] == "Tool my_tool"
