# tests/test_tool_manager_extra.py

"""Additional tests for ToolManager: ctx injection, error handling, build_tool_tree."""

from __future__ import annotations

import sys
import types

import pytest

from commamatrix.components.hook import BeforeToolCallCtx, RunCtx
from commamatrix.components.llm_adapter import ToolCall, ToolCallResult
from commamatrix.components.tool import ToolDescriptor, ToolManager, tool
from commamatrix.core.classes.manager import ServiceInstanceRegistry
from tests.conftest import StubOrigin, stub_agent, stub_origin

# ── ToolManager.call() with ctx injection ────────────────────────────────────


class TestToolManagerCallCtxInjection:
    @pytest.mark.asyncio
    async def test_tool_receives_before_tool_call_ctx(self):
        mod = types.ModuleType("ctx_inject_mod")

        received_ctx = []

        @tool
        async def check_ctx(ctx: BeforeToolCallCtx, x: int) -> str:
            received_ctx.append(ctx)
            return f"got ctx, x={x}"

        check_ctx.__module__ = "ctx_inject_mod"
        mod.check_ctx = check_ctx
        sys.modules["ctx_inject_mod"] = mod
        try:
            agent = stub_agent()
            tm = ToolManager(agent=agent)
            tm.set_scope(["ctx_inject_mod"])
            tm.scan()

            run = RunCtx(agent=agent, origin=stub_origin(), user="u")
            before_ctx = BeforeToolCallCtx(
                run=run,
                tool_call=ToolCall(tool_call_id="tc1", tool_name="ctx_inject_mod_check_ctx", tool_args={"x": 5}),
            )

            result = await tm.call(before_ctx.tool_call, ctx=before_ctx)
            assert result.content == "got ctx, x=5"
            assert len(received_ctx) == 1
            assert received_ctx[0] is before_ctx
        finally:
            del sys.modules["ctx_inject_mod"]

    @pytest.mark.asyncio
    async def test_tool_without_ctx_param_works(self):
        mod = types.ModuleType("no_ctx_mod")

        @tool
        async def simple(x: int) -> int:
            return x + 1

        simple.__module__ = "no_ctx_mod"
        mod.simple = simple
        sys.modules["no_ctx_mod"] = mod
        try:
            agent = stub_agent()
            tm = ToolManager(agent=agent)
            tm.set_scope(["no_ctx_mod"])
            tm.scan()

            tc = ToolCall(tool_call_id="tc1", tool_name="no_ctx_mod_simple", tool_args={"x": 10})
            result = await tm.call(tc)
            assert result.content == 11
        finally:
            del sys.modules["no_ctx_mod"]

    @pytest.mark.asyncio
    async def test_call_with_ctx_none_skips_injection(self):
        mod = types.ModuleType("no_ctx2_mod")

        @tool
        async def simple(x: int) -> int:
            return x * 2

        simple.__module__ = "no_ctx2_mod"
        mod.simple = simple
        sys.modules["no_ctx2_mod"] = mod
        try:
            agent = stub_agent()
            tm = ToolManager(agent=agent)
            tm.set_scope(["no_ctx2_mod"])
            tm.scan()

            tc = ToolCall(tool_call_id="tc1", tool_name="no_ctx2_mod_simple", tool_args={"x": 3})
            result = await tm.call(tc, ctx=None)
            assert result.content == 6
        finally:
            del sys.modules["no_ctx2_mod"]


# ── ToolManager.call() error handling ────────────────────────────────────────


class TestToolManagerCallErrors:
    @pytest.mark.asyncio
    async def test_tool_exception_wrapped_in_result(self):
        mod = types.ModuleType("err_tool_mod")

        @tool
        async def failing(x: int) -> int:
            raise ValueError("tool broke")

        failing.__module__ = "err_tool_mod"
        mod.failing = failing
        sys.modules["err_tool_mod"] = mod
        try:
            agent = stub_agent()
            tm = ToolManager(agent=agent)
            tm.set_scope(["err_tool_mod"])
            tm.scan()

            tc = ToolCall(tool_call_id="tc1", tool_name="err_tool_mod_failing", tool_args={"x": 1})
            result = await tm.call(tc)

            assert "error" in result.content.lower()
            assert "tool broke" in result.content
            assert result.tool_call_id == "tc1"
        finally:
            del sys.modules["err_tool_mod"]

    @pytest.mark.asyncio
    async def test_nonexistent_tool_returns_error(self):
        agent = stub_agent()
        tm = ToolManager(agent=agent)

        tc = ToolCall(tool_call_id="tc1", tool_name="nonexistent", tool_args={})
        result = await tm.call(tc)

        assert "not found" in result.content.lower()
        assert result.tool_call_id == "tc1"

    @pytest.mark.asyncio
    async def test_sync_tool_exception_wrapped(self):
        mod = types.ModuleType("sync_err_mod")

        @tool
        def sync_failing(x: int) -> int:
            raise RuntimeError("sync error")

        sync_failing.__module__ = "sync_err_mod"
        mod.sync_failing = sync_failing
        sys.modules["sync_err_mod"] = mod
        try:
            agent = stub_agent()
            tm = ToolManager(agent=agent)
            tm.set_scope(["sync_err_mod"])
            tm.scan()

            tc = ToolCall(tool_call_id="tc1", tool_name="sync_err_mod_sync_failing", tool_args={"x": 1})
            result = await tm.call(tc)

            assert "error" in result.content.lower()
            assert "sync error" in result.content
        finally:
            del sys.modules["sync_err_mod"]


# ── ToolManager.build_tool_tree ──────────────────────────────────────────────


class TestToolManagerBuildToolTree:
    def test_build_tree_flat(self):
        from tests.conftest import make_tool_descriptor
        d1 = make_tool_descriptor(name="search", alias="web")
        d2 = make_tool_descriptor(name="calc", alias="math")

        tree = ToolManager.build_tool_tree([d1, d2])
        # build_tool_tree returns nested structure: {tools: {alias: {__tools__: [descriptors]}}}
        assert "tools" in tree
        assert "web" in tree["tools"]
        assert "__tools__" in tree["tools"]["web"]
        assert len(tree["tools"]["web"]["__tools__"]) == 1
        assert tree["tools"]["web"]["__tools__"][0]["name"] == "search"

    def test_build_tree_empty(self):
        tree = ToolManager.build_tool_tree([])
        assert tree == {"tools": {}}


# ── ToolManager.find_alias ───────────────────────────────────────────────────


class TestToolManagerFindAlias:
    def test_find_existing_alias(self):
        mod = types.ModuleType("alias_mod")

        @tool
        async def my_fn(x: int) -> int:
            return x

        my_fn.__module__ = "alias_mod"
        mod.my_fn = my_fn
        sys.modules["alias_mod"] = mod
        try:
            agent = stub_agent()
            tm = ToolManager(agent=agent)
            tm.set_scope(["alias_mod"])
            tm.scan()

            tools = tm.find_alias("alias_mod")
            assert len(tools) == 1
            assert tools[0].name == "my_fn"
        finally:
            del sys.modules["alias_mod"]

    def test_find_nonexistent_alias(self):
        agent = stub_agent()
        tm = ToolManager(agent=agent)
        assert tm.find_alias("nonexistent") == []


# ── ToolManager.modules ─────────────────────────────────────────────────────


class TestToolManagerModules:
    def test_modules_returns_unique_list(self):
        mod = types.ModuleType("modules_mod")

        @tool
        async def fn1(x: int) -> int:
            return x

        @tool
        async def fn2(x: int) -> int:
            return x

        fn1.__module__ = "modules_mod"
        fn2.__module__ = "modules_mod"
        mod.fn1 = fn1
        mod.fn2 = fn2
        sys.modules["modules_mod"] = mod
        try:
            agent = stub_agent()
            tm = ToolManager(agent=agent)
            tm.set_scope(["modules_mod"])
            tm.scan()

            modules = tm.modules
            # modules is a property returning dict[str, list[ToolDescriptor]]
            assert "modules_mod" in modules
            assert len(modules["modules_mod"]) == 2
        finally:
            del sys.modules["modules_mod"]


# ── PythonToolSource alias validation ────────────────────────────────────────


class TestToolSourceAliasValidation:
    def test_non_identifier_alias_raises(self):
        from commamatrix.components.tool import PythonToolSource

        mod = types.ModuleType("bad_alias_mod")

        @tool(alias="not valid!")
        async def fn(x: int) -> int:
            return x

        fn.__module__ = "bad_alias_mod"
        mod.fn = fn
        sys.modules["bad_alias_mod"] = mod
        try:
            src = PythonToolSource()
            src.set_scope(["bad_alias_mod"])
            with pytest.raises(ValueError):
                src.scan()
        finally:
            del sys.modules["bad_alias_mod"]


# ── PythonToolSource namespace alias fallback ────────────────────────────────


class TestToolSourceNamespaceFallback:
    def test_alias_falls_back_to_module_suffix(self):
        mod = types.ModuleType("my.deep.module")

        @tool
        async def fn(x: int) -> int:
            return x

        fn.__module__ = "my.deep.module"
        mod.fn = fn
        sys.modules["my.deep.module"] = mod
        try:
            from commamatrix.components.tool import PythonToolSource
            src = PythonToolSource()
            src.set_scope(["my.deep.module"])
            descriptors = src.scan()

            assert len(descriptors) == 1
            assert descriptors[0].alias == "module"
        finally:
            del sys.modules["my.deep.module"]


# ── PythonToolSource.invoke() with ctx ───────────────────────────────────────


class TestToolSourceInvokeWithCtx:
    @pytest.mark.asyncio
    async def test_invoke_passes_ctx_to_tool(self):
        mod = types.ModuleType("invoke_ctx_mod")

        received = []

        @tool
        async def fn(ctx: BeforeToolCallCtx, x: int) -> int:
            received.append(ctx)
            return x

        fn.__module__ = "invoke_ctx_mod"
        mod.fn = fn
        sys.modules["invoke_ctx_mod"] = mod
        try:
            from commamatrix.components.tool import PythonToolSource
            src = PythonToolSource()
            src.set_scope(["invoke_ctx_mod"])
            descriptors = src.scan()

            from commamatrix.core.classes.manager import ServiceInstanceRegistry
            agent = stub_agent()
            run = RunCtx(agent=agent, origin=stub_origin(), user="u")
            before_ctx = BeforeToolCallCtx(
                run=run,
                tool_call=ToolCall(tool_call_id="tc1", tool_name="fn", tool_args={"x": 42}),
            )

            result = await src.invoke(descriptors[0], {"x": 42}, ctx=before_ctx)
            assert result == 42
            assert received[0] is before_ctx
        finally:
            del sys.modules["invoke_ctx_mod"]
