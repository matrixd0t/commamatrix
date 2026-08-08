# tests/test_hook_ordering.py

"""Integration tests for hook ordering with before/after constraints."""

from __future__ import annotations

import weakref
from types import SimpleNamespace

import pytest

from commamatrix.components.hook import (
    HOOK_ATTRIBUTE,
    AfterLlmCallCtx,
    BeforeLlmCallCtx,
    BeforeRunCtx,
    Hook,
    HookDescriptor,
    HookEventType,
    HookManager,
    PythonHookSource,
    after_llm_call,
    before_llm_call,
    before_run,
)
from commamatrix.core.classes.manager import ServiceInstanceRegistry
from commamatrix.core.classes.ordering import CyclicConstraintError


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


# ---------------------------------------------------------------------------
# Hook decorator stamps correct attributes
# ---------------------------------------------------------------------------


class TestHookDecoratorAttributes:
    def test_basic_hook(self):
        @before_run
        def my_hook(ctx): ...

        params = getattr(my_hook, HOOK_ATTRIBUTE)
        assert params["event"] == HookEventType.BEFORE_RUN
        assert params["priority"] == 0
        assert params["before"] == ()
        assert params["after"] == ()

    def test_priority_only(self):
        @before_run(priority=10)
        def my_hook(ctx): ...

        params = getattr(my_hook, HOOK_ATTRIBUTE)
        assert params["priority"] == 10
        assert params["before"] == ()
        assert params["after"] == ()

    def test_before_string(self):
        @before_run(before="other_hook")
        def my_hook(ctx): ...

        params = getattr(my_hook, HOOK_ATTRIBUTE)
        assert params["before"] == ("other_hook",)
        assert params["after"] == ()

    def test_after_string(self):
        @before_run(after="other_hook")
        def my_hook(ctx): ...

        params = getattr(my_hook, HOOK_ATTRIBUTE)
        assert params["after"] == ("other_hook",)

    def test_before_callable(self):
        def other_hook(ctx): ...

        @before_run(before=other_hook)
        def my_hook(ctx): ...

        params = getattr(my_hook, HOOK_ATTRIBUTE)
        assert params["before"] == ("other_hook",)

    def test_before_list_of_strings(self):
        @before_run(before=["a", "b"])
        def my_hook(ctx): ...

        params = getattr(my_hook, HOOK_ATTRIBUTE)
        assert params["before"] == ("a", "b")

    def test_mixed_before_and_after(self):
        @before_run(before="a", after="b")
        def my_hook(ctx): ...

        params = getattr(my_hook, HOOK_ATTRIBUTE)
        assert params["before"] == ("a",)
        assert params["after"] == ("b",)

    def test_priority_with_constraints(self):
        @before_run(priority=5, before="a", after="b")
        def my_hook(ctx): ...

        params = getattr(my_hook, HOOK_ATTRIBUTE)
        assert params["priority"] == 5
        assert params["before"] == ("a",)
        assert params["after"] == ("b",)


# ---------------------------------------------------------------------------
# HookManager._rebuild ordering
# ---------------------------------------------------------------------------


class TestHookManagerRebuild:
    def test_priority_only_descending(self):
        agent = _stub_agent()
        manager = HookManager(agent)
        source = PythonHookSource()
        d1 = _make_descriptor("a", priority=1, source=source)
        d2 = _make_descriptor("b", priority=10, source=source)
        d3 = _make_descriptor("c", priority=5, source=source)
        manager._descriptors = {d.id: d for d in [d1, d2, d3]}
        manager._rebuild()
        names = [d.name for d in manager._handlers["before_run"]]
        assert names == ["b", "c", "a"]

    def test_before_constraint_overrides_priority(self):
        agent = _stub_agent()
        manager = HookManager(agent)
        source = PythonHookSource()
        d1 = _make_descriptor("a", priority=100, source=source)
        d2 = _make_descriptor("b", priority=0, before=("a",), source=source)
        manager._descriptors = {d.id: d for d in [d1, d2]}
        manager._rebuild()
        names = [d.name for d in manager._handlers["before_run"]]
        assert names == ["b", "a"]

    def test_after_constraint(self):
        agent = _stub_agent()
        manager = HookManager(agent)
        source = PythonHookSource()
        d1 = _make_descriptor("a", priority=100, after=("b",), source=source)
        d2 = _make_descriptor("b", priority=0, source=source)
        manager._descriptors = {d.id: d for d in [d1, d2]}
        manager._rebuild()
        names = [d.name for d in manager._handlers["before_run"]]
        assert names == ["b", "a"]

    def test_many_after_same_target_ordered_by_priority(self):
        agent = _stub_agent()
        manager = HookManager(agent)
        source = PythonHookSource()
        d_x = _make_descriptor("x", priority=0, source=source)
        d_a = _make_descriptor("a", priority=5, after=("x",), source=source)
        d_b = _make_descriptor("b", priority=10, after=("x",), source=source)
        manager._descriptors = {d.id: d for d in [d_x, d_a, d_b]}
        manager._rebuild()
        names = [d.name for d in manager._handlers["before_run"]]
        assert names == ["x", "b", "a"]

    def test_events_are_independent(self):
        agent = _stub_agent()
        manager = HookManager(agent)
        source = PythonHookSource()
        d1 = _make_descriptor("a", event="before_run", priority=10, source=source)
        d2 = _make_descriptor("b", event="before_llm_call", priority=0, source=source)
        manager._descriptors = {d.id: d for d in [d1, d2]}
        manager._rebuild()
        assert [d.name for d in manager._handlers["before_run"]] == ["a"]
        assert [d.name for d in manager._handlers["before_llm_call"]] == ["b"]

    def test_unknown_reference_ignored(self):
        agent = _stub_agent()
        manager = HookManager(agent)
        source = PythonHookSource()
        d1 = _make_descriptor("a", priority=10, before=("nonexistent",), source=source)
        d2 = _make_descriptor("b", priority=0, source=source)
        manager._descriptors = {d.id: d for d in [d1, d2]}
        manager._rebuild()
        names = [d.name for d in manager._handlers["before_run"]]
        assert names == ["a", "b"]

    def test_cycle_raises(self):
        agent = _stub_agent()
        manager = HookManager(agent)
        source = PythonHookSource()
        d1 = _make_descriptor("a", before=("b",), source=source)
        d2 = _make_descriptor("b", before=("a",), source=source)
        manager._descriptors = {d.id: d for d in [d1, d2]}
        with pytest.raises(CyclicConstraintError):
            manager._rebuild()

    def test_qualified_module_name_constraint(self):
        agent = _stub_agent()
        manager = HookManager(agent)
        source = PythonHookSource()
        d1 = _make_descriptor("a", module="mod1", before=("mod2.b",), source=source)
        d2 = _make_descriptor("b", module="mod2", priority=100, source=source)
        manager._descriptors = {d.id: d for d in [d1, d2]}
        manager._rebuild()
        names = [d.name for d in manager._handlers["before_run"]]
        assert names == ["a", "b"]


# ---------------------------------------------------------------------------
# HookManager.fire — live execution order
# ---------------------------------------------------------------------------


class TestHookManagerFire:
    @pytest.mark.asyncio
    async def test_fire_calls_in_order(self):
        agent = _stub_agent()
        manager = HookManager(agent)
        source = PythonHookSource()
        call_log: list[str] = []

        async def hook_a(ctx):
            call_log.append("a")

        async def hook_b(ctx):
            call_log.append("b")

        d1 = _make_descriptor("a", priority=100, source=source)
        d2 = _make_descriptor("b", priority=0, before=("a",), source=source)
        source._handlers[d1.id] = hook_a
        source._handlers[d2.id] = hook_b
        manager._descriptors = {d.id: d for d in [d1, d2]}
        manager._rebuild()

        ctx = SimpleNamespace()
        await manager.fire("before_run", ctx)
        assert call_log == ["b", "a"]


# ---------------------------------------------------------------------------
# Manager.scan() atomic rollback on _rebuild failure
# ---------------------------------------------------------------------------


class TestManagerAtomicScan:
    def test_scan_rolls_back_on_rebuild_failure(self):
        from commamatrix.core.classes.manager import Manager

        class BadRebuildManager(Manager[HookDescriptor]):
            fail_next = False

            def _rebuild(self):
                if self.fail_next:
                    self.fail_next = False
                    raise CyclicConstraintError(["a", "b", "a"])

        agent = _stub_agent()
        manager = BadRebuildManager(agent)
        source = PythonHookSource()
        d1 = _make_descriptor("a", priority=10, source=source)
        d2 = _make_descriptor("b", priority=5, source=source)
        source._available = True
        source._scan_results = [d1, d2]

        orig_scan = source.scan

        def controlled_scan():
            return source._scan_results

        source.scan = controlled_scan
        manager.mount(source)
        manager.scan()

        old_fingerprint = manager._fingerprint
        old_descriptor_ids = set(manager._descriptors.keys())

        d3 = _make_descriptor("c", source=source)
        source._scan_results = [d1, d2, d3]
        manager.fail_next = True

        with pytest.raises(CyclicConstraintError):
            manager.scan()

        assert manager._fingerprint == old_fingerprint
        assert set(manager._descriptors.keys()) == old_descriptor_ids
