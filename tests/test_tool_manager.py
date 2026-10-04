# tests/test_tool_manager.py

"""Tests for @tool decorator, ToolManager, PythonToolSource."""

from __future__ import annotations

import sys
import types

import pytest

from commamatrix.components.hook import BeforeToolCallCtx, RunCtx
from commamatrix.components.llm_adapter import ToolCall
from commamatrix.components.tool import (
    TOOL_ATTRIBUTE,
    AmbiguousToolError,
    PythonToolSource,
    ToolDescriptor,
    ToolManager,
    tool,
    tool_max_out_chars,
)
from commamatrix.utils import commamatrix_dir
from tests.conftest import stub_agent, stub_origin


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


class TestToolTruncation:
    def _scan(self, module_name, fn):
        module = types.ModuleType(module_name)
        fn.__module__ = module_name
        setattr(module, fn.__name__, fn)
        sys.modules[module_name] = module
        source = PythonToolSource()
        source.set_scope([module_name])
        return source, source.scan()[0]

    def test_truncation_injects_schema_and_signature(self):
        @tool(truncation=True)
        async def emit() -> str:
            return "x"

        _source, descriptor = self._scan("trunc_schema_mod", emit)
        try:
            properties = descriptor.schema["parameters"]["properties"]
            assert properties["max_out_chars"]["type"] == "integer"
            names = [item["name"] for item in descriptor.meta["signature"]]
            assert "max_out_chars" in names
        finally:
            del sys.modules["trunc_schema_mod"]

    @pytest.mark.asyncio
    async def test_truncation_spills_full_output(self, tmp_path):
        @tool(truncation=True)
        async def emit() -> str:
            return "A" * 50

        source, descriptor = self._scan("trunc_spill_mod", emit)
        try:
            agent = stub_agent()
            agent.config.set(commamatrix_dir, str(tmp_path))
            agent.config.set(tool_max_out_chars, 10)
            ctx = BeforeToolCallCtx(
                run=RunCtx(agent=agent, origin=stub_origin(), user="u"),
                tool_call=ToolCall(tool_call_id="1", tool_name="trunc_spill_mod_emit", tool_args={}),
            )
            result = await source.invoke(descriptor, {}, ctx=ctx)

            assert result.startswith("A" * 10)
            assert "[ shown 10/50 chars, full output available at " in result
            outputs = list((tmp_path / "tool_outputs").glob("trunc_spill_mod_emit_*.txt"))
            assert len(outputs) == 1
            assert outputs[0].read_text(encoding="utf-8") == "A" * 50
        finally:
            del sys.modules["trunc_spill_mod"]

    @pytest.mark.asyncio
    async def test_truncation_explicit_param(self, tmp_path):
        @tool(truncation=True)
        async def emit() -> str:
            return "B" * 30

        source, descriptor = self._scan("trunc_param_mod", emit)
        try:
            agent = stub_agent()
            agent.config.set(commamatrix_dir, str(tmp_path))
            agent.config.set(tool_max_out_chars, 1000)
            ctx = BeforeToolCallCtx(
                run=RunCtx(agent=agent, origin=stub_origin(), user="u"),
                tool_call=ToolCall(tool_call_id="1", tool_name="trunc_param_mod_emit", tool_args={}),
            )
            result = await source.invoke(descriptor, {"max_out_chars": 5}, ctx=ctx)

            assert result.startswith("B" * 5)
            assert "[ shown 5/30 chars" in result
        finally:
            del sys.modules["trunc_param_mod"]

    @pytest.mark.asyncio
    async def test_truncation_leaves_small_output(self, tmp_path):
        @tool(truncation=True)
        async def emit() -> str:
            return "small"

        source, descriptor = self._scan("trunc_small_mod", emit)
        try:
            agent = stub_agent()
            agent.config.set(commamatrix_dir, str(tmp_path))
            agent.config.set(tool_max_out_chars, 1000)
            ctx = BeforeToolCallCtx(
                run=RunCtx(agent=agent, origin=stub_origin(), user="u"),
                tool_call=ToolCall(tool_call_id="1", tool_name="trunc_small_mod_emit", tool_args={}),
            )
            result = await source.invoke(descriptor, {}, ctx=ctx)

            assert result == "small"
            assert not (tmp_path / "tool_outputs").exists()
        finally:
            del sys.modules["trunc_small_mod"]


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
