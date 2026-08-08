# tests/test_hook_extra.py

"""Additional tests for hook system: fire with errors, sync handlers, all event types."""

from __future__ import annotations

import weakref
from types import SimpleNamespace

import pytest

from commamatrix.components.hook import (
    HOOK_ATTRIBUTE,
    AfterLlmCallCtx,
    AfterRunCtx,
    AfterToolCallCtx,
    BeforeLlmCallCtx,
    BeforeRunCtx,
    BeforeSendCtx,
    BeforeToolCallCtx,
    Hook,
    HookDescriptor,
    HookEventType,
    HookManager,
    OnAgentStartCtx,
    OnErrorCtx,
    OnParsedCtx,
    PythonHookSource,
    RunCtx,
    after_llm_call,
    after_run,
    after_tool_call,
    before_llm_call,
    before_run,
    before_send,
    before_tool_call,
    on_agent_start,
    on_error,
    on_parsed,
)
from commamatrix.core.classes.manager import ServiceInstanceRegistry


def _stub_agent() -> SimpleNamespace:
    return SimpleNamespace(services=ServiceInstanceRegistry())


def _make_descriptor(
    name: str,
    module: str = "test_mod",
    event: str = "before_run",
    priority: int = 0,
    before: tuple[str, ...] = (),
    after: tuple[str, ...] = (),
    source: PythonHookSource | None = None,
) -> HookDescriptor:
    if source is None:
        source = PythonHookSource()
    return HookDescriptor(
        id=f"hook://{module}/{name}",
        event=event,
        priority=priority,
        name=name,
        module=module,
        before=before,
        after=after,
        _source_ref=weakref.ref(source),
    )


# ── Fire with exception in handler ──────────────────────────────────────────


class TestHookFireException:
    @pytest.mark.asyncio
    async def test_exception_propagates(self):
        agent = _stub_agent()
        manager = HookManager(agent)
        source = PythonHookSource()

        async def failing_hook(ctx):
            raise ValueError("hook failed")

        d = _make_descriptor("fail", source=source)
        source._handlers[d.id] = failing_hook
        manager._descriptors = {d.id: d}
        manager._rebuild()

        with pytest.raises(ValueError, match="hook failed"):
            await manager.fire("before_run", SimpleNamespace())

    @pytest.mark.asyncio
    async def test_first_hook_fails_stops_remaining(self):
        agent = _stub_agent()
        manager = HookManager(agent)
        source = PythonHookSource()
        call_log: list[str] = []

        async def hook_a(ctx):
            call_log.append("a")
            raise ValueError("fail")

        async def hook_b(ctx):
            call_log.append("b")

        d1 = _make_descriptor("a", priority=10, source=source)
        d2 = _make_descriptor("b", priority=0, source=source)
        source._handlers[d1.id] = hook_a
        source._handlers[d2.id] = hook_b
        manager._descriptors = {d.id: d for d in [d1, d2]}
        manager._rebuild()

        with pytest.raises(ValueError):
            await manager.fire("before_run", SimpleNamespace())

        assert call_log == ["a"]  # b never called


# ── Mixed sync/async handlers ───────────────────────────────────────────────


class TestHookMixedSyncAsync:
    @pytest.mark.asyncio
    async def test_sync_handler_called(self):
        agent = _stub_agent()
        manager = HookManager(agent)
        source = PythonHookSource()
        call_log: list[str] = []

        def sync_hook(ctx):
            call_log.append("sync")

        d = _make_descriptor("sync", source=source)
        source._handlers[d.id] = sync_hook
        manager._descriptors = {d.id: d}
        manager._rebuild()

        await manager.fire("before_run", SimpleNamespace())
        assert call_log == ["sync"]

    @pytest.mark.asyncio
    async def test_mixed_sync_async_in_order(self):
        agent = _stub_agent()
        manager = HookManager(agent)
        source = PythonHookSource()
        call_log: list[str] = []

        def sync_hook(ctx):
            call_log.append("sync")

        async def async_hook(ctx):
            call_log.append("async")

        d1 = _make_descriptor("sync", priority=10, source=source)
        d2 = _make_descriptor("async", priority=0, before=("sync",), source=source)
        source._handlers[d1.id] = sync_hook
        source._handlers[d2.id] = async_hook
        manager._descriptors = {d.id: d for d in [d1, d2]}
        manager._rebuild()

        await manager.fire("before_run", SimpleNamespace())
        assert call_log == ["async", "sync"]


# ── Fire with no handlers ───────────────────────────────────────────────────


class TestHookFireEmpty:
    @pytest.mark.asyncio
    async def test_fire_empty_event(self):
        agent = _stub_agent()
        manager = HookManager(agent)

        # No handlers registered — should not raise
        await manager.fire("before_run", SimpleNamespace())


# ── All hook event type decorators ──────────────────────────────────────────


class TestHookEventTypeDecorators:
    def test_on_agent_start(self):
        @on_agent_start
        def h(ctx): ...
        assert getattr(h, HOOK_ATTRIBUTE)["event"] == HookEventType.ON_AGENT_START

    def test_on_parsed(self):
        @on_parsed
        def h(ctx): ...
        assert getattr(h, HOOK_ATTRIBUTE)["event"] == HookEventType.ON_PARSED

    def test_before_run(self):
        @before_run
        def h(ctx): ...
        assert getattr(h, HOOK_ATTRIBUTE)["event"] == HookEventType.BEFORE_RUN

    def test_before_llm_call(self):
        @before_llm_call
        def h(ctx): ...
        assert getattr(h, HOOK_ATTRIBUTE)["event"] == HookEventType.BEFORE_LLM_CALL

    def test_after_llm_call(self):
        @after_llm_call
        def h(ctx): ...
        assert getattr(h, HOOK_ATTRIBUTE)["event"] == HookEventType.AFTER_LLM_CALL

    def test_before_tool_call(self):
        @before_tool_call
        def h(ctx): ...
        assert getattr(h, HOOK_ATTRIBUTE)["event"] == HookEventType.BEFORE_TOOL_CALL

    def test_after_tool_call(self):
        @after_tool_call
        def h(ctx): ...
        assert getattr(h, HOOK_ATTRIBUTE)["event"] == HookEventType.AFTER_TOOL_CALL

    def test_before_send(self):
        @before_send
        def h(ctx): ...
        assert getattr(h, HOOK_ATTRIBUTE)["event"] == HookEventType.BEFORE_SEND

    def test_on_error(self):
        @on_error
        def h(ctx): ...
        assert getattr(h, HOOK_ATTRIBUTE)["event"] == HookEventType.ON_ERROR

    def test_after_run(self):
        @after_run
        def h(ctx): ...
        assert getattr(h, HOOK_ATTRIBUTE)["event"] == HookEventType.AFTER_RUN


# ── PythonHookSource scanning ───────────────────────────────────────────────


class TestPythonHookSourceScan:
    def test_scan_finds_decorated_functions(self):
        import sys
        import types

        mod = types.ModuleType("hook_scan_test")

        @before_run
        def my_hook(ctx): ...

        my_hook.__module__ = "hook_scan_test"
        mod.my_hook = my_hook
        sys.modules["hook_scan_test"] = mod
        try:
            src = PythonHookSource()
            src.set_scope(["hook_scan_test"])
            descriptors = src.scan()

            assert len(descriptors) == 1
            assert descriptors[0].name == "my_hook"
            assert descriptors[0].event == "before_run"
        finally:
            del sys.modules["hook_scan_test"]

    def test_scan_ignores_non_decorated(self):
        import sys
        import types

        mod = types.ModuleType("hook_scan_ignores")

        def regular_func(ctx): ...

        mod.regular_func = regular_func
        sys.modules["hook_scan_ignores"] = mod
        try:
            src = PythonHookSource()
            src.set_scope(["hook_scan_ignores"])
            assert src.scan() == []
        finally:
            del sys.modules["hook_scan_ignores"]


# ── PythonHookSource.invoke() ───────────────────────────────────────────────


class TestPythonHookSourceInvoke:
    @pytest.mark.asyncio
    async def test_invoke_async_handler(self):
        source = PythonHookSource()
        call_log = []

        async def handler(ctx):
            call_log.append("called")

        d = _make_descriptor("test", source=source)
        source._handlers[d.id] = handler

        await source.invoke(d, SimpleNamespace())
        assert call_log == ["called"]

    @pytest.mark.asyncio
    async def test_invoke_sync_handler(self):
        source = PythonHookSource()
        call_log = []

        def handler(ctx):
            call_log.append("called")

        d = _make_descriptor("test", source=source)
        source._handlers[d.id] = handler

        await source.invoke(d, SimpleNamespace())
        assert call_log == ["called"]
