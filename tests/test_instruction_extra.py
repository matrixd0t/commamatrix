# tests/test_instruction_extra.py

"""Additional tests for instruction system: add_instructions hook end-to-end, sync handlers."""

from __future__ import annotations

import sys
import types

import pytest

from commamatrix.components.dialog import DialogItem, DialogItemType, DialogRole
from commamatrix.components.hook import BeforeLlmCallCtx, RunCtx
from commamatrix.components.instruction import (
    InstructionManager,
    PythonInstructionSource,
    instruction,
    add_instructions,
    InstructionCtx,
)
from commamatrix.core.classes.manager import ServiceInstanceRegistry
from tests.conftest import StubOrigin, stub_origin, make_dialog_item


def _stub_agent():
    from types import SimpleNamespace
    return SimpleNamespace(services=ServiceInstanceRegistry())


# ── add_instructions hook end-to-end ─────────────────────────────────────────


class TestAddInstructionsEndToEnd:
    @pytest.mark.asyncio
    async def test_prepends_system_message(self):
        agent = _stub_agent()
        agent.instruction_manager = InstructionManager(agent=agent)
        source = PythonInstructionSource()

        async def current_date(ctx: InstructionCtx) -> str:
            return "Today is 2025-01-01"

        d = InstructionDescriptor(
            id="instruction://test/current_date",
            name="current_date",
            module="test",
            priority=0,
            _source_ref=weakref.ref(source),
        )
        source._handlers[d.id] = current_date
        agent.instruction_manager._descriptors = {d.id: d}
        agent.instruction_manager._rebuild()

        run = RunCtx(agent=agent, origin=stub_origin(), user="u")
        dialog = [make_dialog_item("Hi", role=DialogRole.USER)]
        ctx = BeforeLlmCallCtx(run=run, dialog=dialog, tools=[])

        await add_instructions(ctx)

        assert len(ctx.dialog) == 2
        assert ctx.dialog[0].role == DialogRole.SYSTEM
        assert ctx.dialog[0].item_type == DialogItemType.INPUT
        assert ctx.dialog[0].content == "Today is 2025-01-01"
        assert ctx.dialog[1].content == "Hi"

    @pytest.mark.asyncio
    async def test_multiple_instructions_joined(self):
        agent = _stub_agent()
        agent.instruction_manager = InstructionManager(agent=agent)
        source = PythonInstructionSource()

        async def inst_a(ctx: InstructionCtx) -> str:
            return "Part A"

        async def inst_b(ctx: InstructionCtx) -> str:
            return "Part B"

        d1 = InstructionDescriptor(id="instruction://test/a", name="a", module="test", priority=10, _source_ref=weakref.ref(source))
        d2 = InstructionDescriptor(id="instruction://test/b", name="b", module="test", priority=0, before=("a",), _source_ref=weakref.ref(source))
        source._handlers[d1.id] = inst_a
        source._handlers[d2.id] = inst_b
        agent.instruction_manager._descriptors = {d1.id: d1, d2.id: d2}
        agent.instruction_manager._rebuild()

        run = RunCtx(agent=agent, origin=stub_origin(), user="u")
        dialog = [make_dialog_item("Hi", role=DialogRole.USER)]
        ctx = BeforeLlmCallCtx(run=run, dialog=dialog, tools=[])

        await add_instructions(ctx)

        assert len(ctx.dialog) == 2
        assert ctx.dialog[0].content == "Part B\n\nPart A"

    @pytest.mark.asyncio
    async def test_no_instructions_does_nothing(self):
        agent = _stub_agent()
        agent.instruction_manager = InstructionManager(agent=agent)

        run = RunCtx(agent=agent, origin=stub_origin(), user="u")
        dialog = [make_dialog_item("Hi", role=DialogRole.USER)]
        ctx = BeforeLlmCallCtx(run=run, dialog=dialog, tools=[])

        await add_instructions(ctx)

        assert len(ctx.dialog) == 1
        assert ctx.dialog[0].content == "Hi"

    @pytest.mark.asyncio
    async def test_none_instructions_skipped(self):
        agent = _stub_agent()
        agent.instruction_manager = InstructionManager(agent=agent)
        source = PythonInstructionSource()

        async def inst_none(ctx: InstructionCtx) -> None:
            return None

        async def inst_something(ctx: InstructionCtx) -> str:
            return "Something"

        d1 = InstructionDescriptor(id="instruction://test/none", name="none", module="test", priority=10, _source_ref=weakref.ref(source))
        d2 = InstructionDescriptor(id="instruction://test/something", name="something", module="test", priority=0, _source_ref=weakref.ref(source))
        source._handlers[d1.id] = inst_none
        source._handlers[d2.id] = inst_something
        agent.instruction_manager._descriptors = {d1.id: d1, d2.id: d2}
        agent.instruction_manager._rebuild()

        run = RunCtx(agent=agent, origin=stub_origin(), user="u")
        dialog = [make_dialog_item("Hi", role=DialogRole.USER)]
        ctx = BeforeLlmCallCtx(run=run, dialog=dialog, tools=[])

        await add_instructions(ctx)

        assert len(ctx.dialog) == 2
        assert ctx.dialog[0].content == "Something"

    @pytest.mark.asyncio
    async def test_system_item_has_origin_and_no_item_id(self):
        agent = _stub_agent()
        agent.instruction_manager = InstructionManager(agent=agent)
        source = PythonInstructionSource()

        async def inst(ctx: InstructionCtx) -> str:
            return "Test"

        d = InstructionDescriptor(id="instruction://test/inst", name="inst", module="test", _source_ref=weakref.ref(source))
        source._handlers[d.id] = inst
        agent.instruction_manager._descriptors = {d.id: d}
        agent.instruction_manager._rebuild()

        origin = stub_origin()
        run = RunCtx(agent=agent, origin=origin, user="u")
        dialog = [make_dialog_item("Hi", role=DialogRole.USER)]
        ctx = BeforeLlmCallCtx(run=run, dialog=dialog, tools=[])

        await add_instructions(ctx)

        system_item = ctx.dialog[0]
        assert system_item.origin is origin
        assert system_item.item_id is None


# ── Mixed sync/async instruction handlers ────────────────────────────────────


class TestInstructionMixedSyncAsync:
    @pytest.mark.asyncio
    async def test_sync_handler(self):
        agent = _stub_agent()
        agent.instruction_manager = InstructionManager(agent=agent)
        source = PythonInstructionSource()

        def sync_inst(ctx: InstructionCtx) -> str:
            return "sync result"

        d = InstructionDescriptor(id="instruction://test/sync", name="sync", module="test", _source_ref=weakref.ref(source))
        source._handlers[d.id] = sync_inst
        agent.instruction_manager._descriptors = {d.id: d}
        agent.instruction_manager._rebuild()

        run = RunCtx(agent=agent, origin=stub_origin(), user="u")
        result = await agent.instruction_manager.collect(run)
        assert result == ["sync result"]

    @pytest.mark.asyncio
    async def test_mixed_sync_async_handlers(self):
        agent = _stub_agent()
        agent.instruction_manager = InstructionManager(agent=agent)
        source = PythonInstructionSource()

        def sync_inst(ctx: InstructionCtx) -> str:
            return "sync"

        async def async_inst(ctx: InstructionCtx) -> str:
            return "async"

        d1 = InstructionDescriptor(id="instruction://test/sync", name="sync", module="test", priority=10, _source_ref=weakref.ref(source))
        d2 = InstructionDescriptor(id="instruction://test/async", name="async", module="test", priority=0, before=("sync",), _source_ref=weakref.ref(source))
        source._handlers[d1.id] = sync_inst
        source._handlers[d2.id] = async_inst
        agent.instruction_manager._descriptors = {d1.id: d1, d2.id: d2}
        agent.instruction_manager._rebuild()

        run = RunCtx(agent=agent, origin=stub_origin(), user="u")
        result = await agent.instruction_manager.collect(run)
        assert result == ["async", "sync"]


# ── InstructionManager.set_scope ─────────────────────────────────────────────


class TestInstructionManagerSetScope:
    def test_set_scope_propagates(self):
        agent = _stub_agent()
        manager = InstructionManager(agent=agent)
        assert manager._python_source is not None

        manager.set_scope(["mod1", "mod2"])
        # Verify scope was set
        assert manager._python_source._scope == ["mod1", "mod2"]


# ── Imports needed for tests ─────────────────────────────────────────────────

import weakref
from commamatrix.components.instruction import InstructionDescriptor
