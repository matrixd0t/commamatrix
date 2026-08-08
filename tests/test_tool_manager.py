# tests/test_tool_manager.py

"""Tests for @tool decorator, ToolManager, PythonToolSource."""

from __future__ import annotations

import sys
import types

import pytest

from commamatrix.components.llm_adapter import ToolCall, ToolCallResult
from commamatrix.components.tool import (
    TOOL_ATTRIBUTE,
    AmbiguousToolError,
    PythonToolSource,
    ToolDescriptor,
    ToolManager,
    tool,
)
from commamatrix.core.classes.manager import ServiceInstanceRegistry
from tests.conftest import stub_agent


class TestToolDecorator:
    def test_bare_decorator(self):
        @tool
        def my_fn(x: int) -> int:
            return x

        assert hasattr(my_fn, TOOL_ATTRIBUTE)
        meta = getattr(my_fn, TOOL_ATTRIBUTE)
        assert meta == {}

    def test_with_meta(self):
        @tool(alias="my_mod", version=2)
        def my_fn(x: int) -> int:
            return x

        meta = getattr(my_fn, TOOL_ATTRIBUTE)
        assert meta["alias"] == "my_mod"
        assert meta["version"] == 2

    def test_preserves_function(self):
        @tool
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        assert add(1, 2) == 3
        assert add.__name__ == "add"


class TestPythonToolSource:
    def test_scan_finds_decorated(self):
        mod = types.ModuleType("pt_test_mod")

        @tool
        def hello(name: str) -> str:
            """Say hello."""
            return f"hi {name}"

        hello.__module__ = "pt_test_mod"
        mod.hello = hello
        sys.modules["pt_test_mod"] = mod
        try:
            src = PythonToolSource()
            src.set_scope(["pt_test_mod"])
            descriptors = src.scan()
            assert len(descriptors) == 1
            assert descriptors[0].name == "hello"
        finally:
            del sys.modules["pt_test_mod"]

    def test_scan_skips_re_export(self):
        @tool
        def foreign(x: int) -> int:
            return x

        foreign.__module__ = "other_module"

        mod = types.ModuleType("pt_reexport")
        mod.foreign = foreign
        sys.modules["pt_reexport"] = mod
        try:
            src = PythonToolSource()
            src.set_scope(["pt_reexport"])
            assert src.scan() == []
        finally:
            del sys.modules["pt_reexport"]

    @pytest.mark.asyncio
    async def test_invoke_sync_tool(self):
        mod = types.ModuleType("pt_invoke_mod")

        @tool
        def add(a: int, b: int) -> int:
            return a + b

        add.__module__ = "pt_invoke_mod"
        mod.add = add
        sys.modules["pt_invoke_mod"] = mod
        try:
            src = PythonToolSource()
            src.set_scope(["pt_invoke_mod"])
            descriptors = src.scan()
            result = await src.invoke(descriptors[0], {"a": 1, "b": 2})
            assert result == 3
        finally:
            del sys.modules["pt_invoke_mod"]

    @pytest.mark.asyncio
    async def test_invoke_async_tool(self):
        mod = types.ModuleType("pt_async_mod")

        @tool
        async def greet(name: str) -> str:
            return f"hello {name}"

        greet.__module__ = "pt_async_mod"
        mod.greet = greet
        sys.modules["pt_async_mod"] = mod
        try:
            src = PythonToolSource()
            src.set_scope(["pt_async_mod"])
            descriptors = src.scan()
            result = await src.invoke(descriptors[0], {"name": "world"})
            assert result == "hello world"
        finally:
            del sys.modules["pt_async_mod"]


class TestToolManager:
    def test_public_name_with_alias(self):
        from tests.conftest import make_tool_descriptor

        agent = stub_agent()
        tm = ToolManager(agent=agent)
        d = make_tool_descriptor(name="search", alias="web")
        assert tm.public_name(d) == "web_search"

    def test_public_name_no_alias(self):
        from tests.conftest import make_tool_descriptor

        agent = stub_agent()
        tm = ToolManager(agent=agent)
        d = make_tool_descriptor(name="search", alias="")
        assert tm.public_name(d) == "search"

    def test_resolve_existing(self):
        mod = types.ModuleType("tm_test_mod")

        @tool
        def my_fn(x: int) -> int:
            return x

        my_fn.__module__ = "tm_test_mod"
        mod.my_fn = my_fn
        sys.modules["tm_test_mod"] = mod
        try:
            agent = stub_agent()
            tm = ToolManager(agent=agent)
            tm.set_scope(["tm_test_mod"])
            tm.scan()
            d = tm.resolve("tm_test_mod_my_fn")
            assert d is not None
            assert d.name == "my_fn"
        finally:
            del sys.modules["tm_test_mod"]

    def test_resolve_nonexistent(self):
        agent = stub_agent()
        tm = ToolManager(agent=agent)
        assert tm.resolve("nonexistent") is None

    def test_ambiguous_tool_raises(self):
        from tests.conftest import make_tool_descriptor

        agent = stub_agent()
        tm = ToolManager(agent=agent)
        d1 = make_tool_descriptor(name="fn", alias="a", namespace="mod1")
        d2 = make_tool_descriptor(name="fn", alias="a", namespace="mod2")
        d1 = ToolDescriptor(
            id="python://mod1/fn",
            namespace="mod1",
            alias="a",
            name="fn",
            doc="",
            schema={},
            meta={},
            _source_ref=d1._source_ref,
        )
        d2 = ToolDescriptor(
            id="python://mod2/fn",
            namespace="mod2",
            alias="a",
            name="fn",
            doc="",
            schema={},
            meta={},
            _source_ref=d2._source_ref,
        )
        tm._descriptors = {d1.id: d1, d2.id: d2}
        tm._rebuild()
        with pytest.raises(AmbiguousToolError):
            tm.resolve("a_fn")

    @pytest.mark.asyncio
    async def test_call_tool(self):
        mod = types.ModuleType("tm_call_mod")

        @tool
        async def double(n: int) -> int:
            return n * 2

        double.__module__ = "tm_call_mod"
        mod.double = double
        sys.modules["tm_call_mod"] = mod
        try:
            agent = stub_agent()
            tm = ToolManager(agent=agent)
            tm.set_scope(["tm_call_mod"])
            tm.scan()
            tc = ToolCall(
                tool_call_id="1", tool_name="tm_call_mod_double", tool_args={"n": 5}
            )
            result = await tm.call(tc)
            assert result.content == 10
        finally:
            del sys.modules["tm_call_mod"]

    @pytest.mark.asyncio
    async def test_call_nonexistent_tool(self):
        agent = stub_agent()
        tm = ToolManager(agent=agent)
        tc = ToolCall(tool_call_id="1", tool_name="missing", tool_args={})
        result = await tm.call(tc)
        assert "not found" in result.content.lower()

    def test_schemas(self):
        mod = types.ModuleType("tm_schema_mod")

        @tool
        def fn(x: int) -> int:
            """Test."""
            return x

        fn.__module__ = "tm_schema_mod"
        mod.fn = fn
        sys.modules["tm_schema_mod"] = mod
        try:
            agent = stub_agent()
            tm = ToolManager(agent=agent)
            tm.set_scope(["tm_schema_mod"])
            tm.scan()
            schemas = tm.schemas()
            assert len(schemas) == 1
            assert schemas[0]["name"] == "tm_schema_mod_fn"
        finally:
            del sys.modules["tm_schema_mod"]
