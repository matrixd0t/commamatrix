# tests/test_instruction.py

"""Tests for the instruction system: decorator, lifecycle, ordering, and hook."""

from __future__ import annotations

import weakref
from types import SimpleNamespace

import pytest

from commamatrix.core.classes.ordering import CyclicConstraintError
from commamatrix.core.classes.manager import ServiceInstanceRegistry
from commamatrix.components.instruction import (
    INSTRUCTION_ATTRIBUTE,
    Instruction,
    InstructionCtx,
    InstructionDescriptor,
    InstructionManager,
    PythonInstructionSource,
    instruction,
    add_instructions,
)
from commamatrix.components.hook import HOOK_ATTRIBUTE, HookEventType


def _stub_agent() -> SimpleNamespace:
    return SimpleNamespace(services=ServiceInstanceRegistry())


def _make_descriptor(
    name: str,
    module: str = "test_mod",
    priority: int = 0,
    before: tuple[str, ...] = (),
    after: tuple[str, ...] = (),
    source: PythonInstructionSource | None = None,
) -> InstructionDescriptor:
    if source is None:
        source = PythonInstructionSource()
    return InstructionDescriptor(
        id=f"instruction://{module}/{name}",
        name=name,
        module=module,
        priority=priority,
        before=before,
        after=after,
        _source_ref=weakref.ref(source),
    )


# ---------------------------------------------------------------------------
# @instruction decorator stamps correct attributes
# ---------------------------------------------------------------------------


class TestInstructionDecorator:
    def test_bare_decorator(self):
        @instruction
        def current_date(ctx):
            return "2025-01-01"

        params = getattr(current_date, INSTRUCTION_ATTRIBUTE)
        assert params["priority"] == 0
        assert params["before"] == ()
        assert params["after"] == ()

    def test_with_priority(self):
        @instruction(priority=10)
        def my_inst(ctx):
            return "hello"

        params = getattr(my_inst, INSTRUCTION_ATTRIBUTE)
        assert params["priority"] == 10
        assert params["before"] == ()
        assert params["after"] == ()

    def test_with_before_string(self):
        @instruction(before="other")
        def my_inst(ctx):
            return "hello"

        params = getattr(my_inst, INSTRUCTION_ATTRIBUTE)
        assert params["before"] == ("other",)

    def test_with_after_callable(self):
        def other(ctx): ...

        @instruction(after=other)
        def my_inst(ctx):
            return "hello"

        params = getattr(my_inst, INSTRUCTION_ATTRIBUTE)
        assert params["after"] == ("other",)

    def test_with_before_list(self):
        @instruction(before=["a", "b"])
        def my_inst(ctx):
            return "hello"

        params = getattr(my_inst, INSTRUCTION_ATTRIBUTE)
        assert params["before"] == ("a", "b")

    def test_mixed_constraints_and_priority(self):
        @instruction(priority=5, before="a", after=["b", "c"])
        def my_inst(ctx):
            return "hello"

        params = getattr(my_inst, INSTRUCTION_ATTRIBUTE)
        assert params["priority"] == 5
        assert params["before"] == ("a",)
        assert params["after"] == ("b", "c")


# ---------------------------------------------------------------------------
# InstructionManager._rebuild ordering
# ---------------------------------------------------------------------------


class TestInstructionManagerRebuild:
    def test_priority_descending(self):
        agent = _stub_agent()
        manager = InstructionManager(agent)
        source = PythonInstructionSource()
        d1 = _make_descriptor("a", priority=1, source=source)
        d2 = _make_descriptor("b", priority=10, source=source)
        d3 = _make_descriptor("c", priority=5, source=source)
        manager._descriptors = {d.id: d for d in [d1, d2, d3]}
        manager._rebuild()
        names = [d.name for d in manager._ordered]
        assert names == ["b", "c", "a"]

    def test_before_overrides_priority(self):
        agent = _stub_agent()
        manager = InstructionManager(agent)
        source = PythonInstructionSource()
        d1 = _make_descriptor("a", priority=100, source=source)
        d2 = _make_descriptor("b", priority=0, before=("a",), source=source)
        manager._descriptors = {d.id: d for d in [d1, d2]}
        manager._rebuild()
        names = [d.name for d in manager._ordered]
        assert names == ["b", "a"]

    def test_after_constraint(self):
        agent = _stub_agent()
        manager = InstructionManager(agent)
        source = PythonInstructionSource()
        d1 = _make_descriptor("a", priority=100, after=("b",), source=source)
        d2 = _make_descriptor("b", priority=0, source=source)
        manager._descriptors = {d.id: d for d in [d1, d2]}
        manager._rebuild()
        names = [d.name for d in manager._ordered]
        assert names == ["b", "a"]

    def test_unknown_ref_ignored(self):
        agent = _stub_agent()
        manager = InstructionManager(agent)
        source = PythonInstructionSource()
        d1 = _make_descriptor("a", priority=10, before=("nonexistent",), source=source)
        d2 = _make_descriptor("b", priority=0, source=source)
        manager._descriptors = {d.id: d for d in [d1, d2]}
        manager._rebuild()
        names = [d.name for d in manager._ordered]
        assert names == ["a", "b"]

    def test_cycle_raises(self):
        agent = _stub_agent()
        manager = InstructionManager(agent)
        source = PythonInstructionSource()
        d1 = _make_descriptor("a", before=("b",), source=source)
        d2 = _make_descriptor("b", before=("a",), source=source)
        manager._descriptors = {d.id: d for d in [d1, d2]}
        with pytest.raises(CyclicConstraintError):
            manager._rebuild()

    def test_qualified_module_name(self):
        agent = _stub_agent()
        manager = InstructionManager(agent)
        source = PythonInstructionSource()
        d1 = _make_descriptor("a", module="mod1", before=("mod2.b",), source=source)
        d2 = _make_descriptor("b", module="mod2", priority=100, source=source)
        manager._descriptors = {d.id: d for d in [d1, d2]}
        manager._rebuild()
        names = [d.name for d in manager._ordered]
        assert names == ["a", "b"]


# ---------------------------------------------------------------------------
# InstructionManager.collect — live execution
# ---------------------------------------------------------------------------


class TestInstructionManagerCollect:
    @pytest.mark.asyncio
    async def test_collect_in_order(self):
        agent = _stub_agent()
        manager = InstructionManager(agent)
        source = PythonInstructionSource()

        async def inst_a(ctx):
            return "A"

        async def inst_b(ctx):
            return "B"

        d1 = _make_descriptor("a", priority=10, source=source)
        d2 = _make_descriptor("b", priority=0, before=("a",), source=source)
        source._handlers[d1.id] = inst_a
        source._handlers[d2.id] = inst_b
        manager._descriptors = {d.id: d for d in [d1, d2]}
        manager._rebuild()

        run = SimpleNamespace()
        result = await manager.collect(run)
        assert result == ["B", "A"]

    @pytest.mark.asyncio
    async def test_collect_skips_none(self):
        agent = _stub_agent()
        manager = InstructionManager(agent)
        source = PythonInstructionSource()

        async def inst_a(ctx):
            return "A"

        async def inst_none(ctx):
            return None

        d1 = _make_descriptor("a", priority=10, source=source)
        d2 = _make_descriptor("none", priority=0, source=source)
        source._handlers[d1.id] = inst_a
        source._handlers[d2.id] = inst_none
        manager._descriptors = {d.id: d for d in [d1, d2]}
        manager._rebuild()

        run = SimpleNamespace()
        result = await manager.collect(run)
        assert result == ["A"]

    @pytest.mark.asyncio
    async def test_collect_empty(self):
        agent = _stub_agent()
        manager = InstructionManager(agent)
        run = SimpleNamespace()
        result = await manager.collect(run)
        assert result == []


# ---------------------------------------------------------------------------
# PythonInstructionSource scanning
# ---------------------------------------------------------------------------


class TestPythonInstructionSource:
    def test_scan_finds_decorated_functions(self):
        source = PythonInstructionSource()
        source.set_scope(["test_instruction_module"])

        import types
        mod = types.ModuleType("test_instruction_module")

        @instruction
        def my_inst(ctx):
            return "hello"

        my_inst.__module__ = "test_instruction_module"
        mod.my_inst = my_inst
        import sys
        sys.modules["test_instruction_module"] = mod
        try:
            descriptors = source.scan()
            assert len(descriptors) == 1
            assert descriptors[0].name == "my_inst"
            assert descriptors[0].module == "test_instruction_module"
        finally:
            del sys.modules["test_instruction_module"]

    def test_scan_ignores_non_decorated(self):
        source = PythonInstructionSource()
        source.set_scope(["test_instruction_module2"])

        import types
        mod = types.ModuleType("test_instruction_module2")

        def regular_func(ctx):
            return "nope"

        mod.regular_func = regular_func
        import sys
        sys.modules["test_instruction_module2"] = mod
        try:
            descriptors = source.scan()
            assert len(descriptors) == 0
        finally:
            del sys.modules["test_instruction_module2"]


# ---------------------------------------------------------------------------
# add_instructions hook attribute
# ---------------------------------------------------------------------------


class TestAddInstructionsHook:
    def test_stamps_hook_attribute(self):
        params = getattr(add_instructions, HOOK_ATTRIBUTE)
        assert params["event"] == HookEventType.BEFORE_LLM_CALL
        assert params["priority"] == 0
        assert params["before"] == ()
        assert params["after"] == ()
