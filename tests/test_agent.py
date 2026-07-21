# tests/test_agent.py

"""Tests for Agent lifecycle: start, stop, add_extensions, remove_extensions, _split_runs."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from commamatrix.components.config import Config, ConfigField
from commamatrix.components.dialog import DialogItem, DialogItemType, DialogRole
from commamatrix.components.hook import RunCtx
from commamatrix.core.agent.agent import Agent
from tests.conftest import StubOrigin, stub_origin, make_dialog_item


class TestAgentInit:
    def test_creates_managers(self):
        agent = Agent(config={}, auto_load_main=False)
        assert agent.tool_manager is not None
        assert agent.hook_manager is not None
        assert agent.instruction_manager is not None
        assert agent.llm_adapter is not None
        assert agent.storage is not None
        assert agent.file_storage is not None
        assert agent.service_manager is not None
        assert agent.connector_manager is not None

    def test_config_from_dict(self):
        f = ConfigField[str](name="k", default="v")
        agent = Agent(config={f: "val"}, auto_load_main=False)
        assert agent.config.get(f) == "val"

    def test_config_from_config_object(self):
        cfg = Config()
        agent = Agent(config=cfg, auto_load_main=False)
        assert agent.config is cfg

    def test_not_started_initially(self):
        agent = Agent(config={}, auto_load_main=False)
        assert agent._started is False

    def test_extension_scope_empty_initially(self):
        agent = Agent(config={}, auto_load_main=False)
        assert agent._extension_scope == []


class TestAgentExtensions:
    @pytest.mark.asyncio
    async def test_add_extension_by_string(self):
        agent = Agent(config={}, auto_load_main=False)
        result = await agent.add_extensions("os")
        assert "os" in agent._extension_scope
        assert result == ["os"]

    @pytest.mark.asyncio
    async def test_add_extension_by_module(self):
        agent = Agent(config={}, auto_load_main=False)
        import os
        result = await agent.add_extensions(os)
        assert "os" in agent._extension_scope
        assert result == ["os"]

    @pytest.mark.asyncio
    async def test_add_extension_no_duplicates(self):
        agent = Agent(config={}, auto_load_main=False)
        await agent.add_extensions("os")
        await agent.add_extensions("os")
        assert agent._extension_scope.count("os") == 1

    @pytest.mark.asyncio
    async def test_add_extension_includes_submodules(self):
        agent = Agent(config={}, auto_load_main=False)
        await agent.add_extensions("json")
        assert "json" in agent._extension_scope

    @pytest.mark.asyncio
    async def test_add_multiple(self):
        agent = Agent(config={}, auto_load_main=False)
        result = await agent.add_extensions("os", "json")
        assert "os" in agent._extension_scope
        assert "json" in agent._extension_scope
        assert set(result) == {"os", "json"}

    @pytest.mark.asyncio
    async def test_add_skips_invalid(self):
        agent = Agent(config={}, auto_load_main=False)
        result = await agent.add_extensions(42, "os")
        assert result == ["os"]
        assert "os" in agent._extension_scope

    @pytest.mark.asyncio
    async def test_add_empty(self):
        agent = Agent(config={}, auto_load_main=False)
        result = await agent.add_extensions()
        assert result == []
        assert agent._extension_scope == []

    @pytest.mark.asyncio
    async def test_remove_extension(self):
        agent = Agent(config={}, auto_load_main=False)
        await agent.add_extensions("os")
        assert "os" in agent._extension_scope
        result = await agent.remove_extensions("os")
        assert "os" not in agent._extension_scope
        assert result == ["os"]

    @pytest.mark.asyncio
    async def test_remove_multiple(self):
        agent = Agent(config={}, auto_load_main=False)
        await agent.add_extensions("os", "json")
        result = await agent.remove_extensions("os", "json")
        assert "os" not in agent._extension_scope
        assert "json" not in agent._extension_scope
        assert set(result) == {"os", "json"}

    @pytest.mark.asyncio
    async def test_remove_skips_not_in_scope(self):
        agent = Agent(config={}, auto_load_main=False)
        result = await agent.remove_extensions("os")
        assert result == []

    @pytest.mark.asyncio
    async def test_remove_skips_invalid(self):
        agent = Agent(config={}, auto_load_main=False)
        await agent.add_extensions("os")
        result = await agent.remove_extensions(42, "os")
        assert result == ["os"]

    @pytest.mark.asyncio
    async def test_remove_empty(self):
        agent = Agent(config={}, auto_load_main=False)
        result = await agent.remove_extensions()
        assert result == []

    def test_resolve_module_name_string(self):
        assert Agent._resolve_module_name("os") == "os"

    def test_resolve_module_name_module(self):
        import os
        assert Agent._resolve_module_name(os) == "os"

    def test_resolve_module_name_invalid(self):
        assert Agent._resolve_module_name(42) is None


class TestAgentLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        agent = Agent(config={}, auto_load_main=False)
        await agent.start()
        assert agent._started is True
        await agent.stop()
        assert agent._started is False

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self):
        agent = Agent(config={}, auto_load_main=False)
        await agent.start()
        await agent.start()
        assert agent._started is True
        await agent.stop()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with Agent(config={}, auto_load_main=False) as agent:
            assert agent._started is True
        assert agent._started is False

    @pytest.mark.asyncio
    async def test_auto_load_main(self):
        agent = Agent(config={}, auto_load_main=True)
        await agent.start()
        assert "__main__" in agent._extension_scope
        await agent.stop()

    @pytest.mark.asyncio
    async def test_auto_load_defaults(self):
        agent = Agent(config={}, auto_load_main=False)
        await agent.start()
        scope_str = ",".join(agent._extension_scope)
        assert "sqlite" in scope_str
        assert "fs" in scope_str
        await agent.stop()


class TestAgentSplitRuns:
    def test_single_origin(self):
        agent = Agent(config={}, auto_load_main=False)
        origin = stub_origin()
        items = [
            make_dialog_item("a", origin=origin),
            make_dialog_item("b", origin=origin),
        ]
        from commamatrix.components.hook import OnParsedCtx
        ctx = OnParsedCtx(
            agent=agent,
            connector=None,
            raw={},
            dialog_items=items,
        )
        runs = agent._split_runs(ctx)
        assert len(runs) == 1
        assert len(runs[0][1]) == 2

    def test_multiple_origins(self):
        agent = Agent(config={}, auto_load_main=False)
        o1 = stub_origin("chat1")
        o2 = stub_origin("chat2")
        items = [
            make_dialog_item("a", origin=o1),
            make_dialog_item("b", origin=o2),
        ]
        from commamatrix.components.hook import OnParsedCtx
        ctx = OnParsedCtx(
            agent=agent,
            connector=None,
            raw={},
            dialog_items=items,
        )
        runs = agent._split_runs(ctx)
        assert len(runs) == 2


class TestAgentScopeHasAttribute:
    def test_finds_attribute(self):
        agent = Agent(config={}, auto_load_main=False)
        mod = types.ModuleType("test_scope_attr")
        class Svc:
            __commamatrix_service__ = True
        mod.Svc = Svc
        sys.modules["test_scope_attr"] = mod
        agent._extension_scope.append("test_scope_attr")
        try:
            assert agent._scope_has_attribute("__commamatrix_service__") is True
        finally:
            del sys.modules["test_scope_attr"]

    def test_does_not_find_attribute(self):
        agent = Agent(config={}, auto_load_main=False)
        assert agent._scope_has_attribute("__nonexistent__") is False


class TestAgentValidateResponse:
    def test_error_stop_raises(self):
        from commamatrix.components.llm_adapter import LLMResponse, StopReason, LLMResponseError
        agent = Agent(config={}, auto_load_main=False)
        resp = LLMResponse(stop_reason=StopReason.ERROR)
        with pytest.raises(LLMResponseError):
            agent._validate_response(resp, None)

    def test_length_stop_raises(self):
        from commamatrix.components.llm_adapter import LLMResponse, StopReason, LLMTruncatedError
        agent = Agent(config={}, auto_load_main=False)
        resp = LLMResponse(stop_reason=StopReason.LENGTH)
        with pytest.raises(LLMTruncatedError):
            agent._validate_response(resp, None)

    def test_end_turn_ok(self):
        from commamatrix.components.llm_adapter import LLMResponse, StopReason
        agent = Agent(config={}, auto_load_main=False)
        resp = LLMResponse(stop_reason=StopReason.END_TURN)
        agent._validate_response(resp, None)
