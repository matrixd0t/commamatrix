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
from commamatrix.components.server import http_port
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

    def test_service_is_exported_from_package_root(self):
        from commamatrix import Service
        from commamatrix.core.classes.service import Service as CoreService

        assert Service is CoreService

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

    def test_extension_scope_empty_when_plugin_autoload_disabled(self):
        agent = Agent(config={}, auto_load_main=False, auto_load_plugins=False)
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
    async def test_path_extension_uses_filename_as_tool_alias(self, tmp_path):
        path = tmp_path / "coding_agent.py"
        path.write_text(
            "from commamatrix import tool\n\n"
            "@tool\n"
            "async def search(query: str) -> str:\n"
            "    return query\n",
            encoding="utf-8",
        )
        agent = Agent(config={}, auto_load_main=False)
        await agent.add_extensions(str(path))
        await agent.start()
        try:
            assert agent.tool_manager.has_module("coding_agent")
            assert agent.tool_manager.resolve("coding_agent_search") is not None
            assert all(
                not name.startswith("_commamatrix_path_")
                for name in agent.extension_scope
            )
        finally:
            await agent.stop()

    @pytest.mark.asyncio
    async def test_reload_package_rebuilds_all_scope_modules(self, tmp_path):
        package = tmp_path / "reload_probe"
        package.mkdir()
        (package / "__init__.py").write_text(
            "from . import tools\n",
            encoding="utf-8",
        )
        (package / "tools.py").write_text(
            "from commamatrix import tool\n\n"
            "@tool(alias=\"reload_probe\")\n"
            "async def ping() -> str:\n"
            "    return \"pong\"\n",
            encoding="utf-8",
        )
        agent = Agent(config={}, auto_load_main=False)
        await agent.add_extensions(str(package))
        await agent.start()
        try:
            assert "reload_probe" in agent.extension_scope
            assert "reload_probe.tools" in agent.extension_scope
            assert agent.tool_manager.resolve("reload_probe_ping") is not None

            await agent.reload_extensions(str(package))

            assert "reload_probe" in agent.extension_scope
            assert "reload_probe.tools" in agent.extension_scope
            assert agent.tool_manager.resolve("reload_probe_ping") is not None
        finally:
            await agent.stop()

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
    async def test_add_reports_invalid_path_and_keeps_scope(self, tmp_path):
        agent = Agent(
            config={}, auto_load_main=False, auto_load_plugins=False
        )
        missing = tmp_path / "missing_extension.py"

        with pytest.raises(RuntimeError, match="Failed to process extension"):
            await agent.add_extensions(str(missing))

        assert agent._extension_scope == []

    @pytest.mark.asyncio
    async def test_add_empty(self):
        agent = Agent(
            config={}, auto_load_main=False, auto_load_plugins=False
        )
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
        agent = Agent(config={http_port: 0}, auto_load_main=False)
        await agent.start()
        assert agent._started is True
        await agent.stop()
        assert agent._started is False

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self):
        agent = Agent(config={http_port: 0}, auto_load_main=False)
        await agent.start()
        await agent.start()
        assert agent._started is True
        await agent.stop()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with Agent(config={http_port: 0}, auto_load_main=False) as agent:
            assert agent._started is True
        assert agent._started is False

    @pytest.mark.asyncio
    async def test_auto_load_main(self):
        agent = Agent(config={http_port: 0}, auto_load_main=True)
        await agent.start()
        assert "__main__" in agent._extension_scope
        await agent.stop()

    @pytest.mark.asyncio
    async def test_auto_load_defaults(self):
        agent = Agent(config={http_port: 0}, auto_load_main=False)
        await agent.start()
        scope_str = ",".join(agent._extension_scope)
        assert "components.instruction" in scope_str
        assert "builtin.sql.sqlite_storage" in scope_str
        assert "builtin.simple_fs" in scope_str
        await agent.stop()

    @pytest.mark.asyncio
    async def test_auto_load_plugins(self, tmp_path, monkeypatch):
        plugin_root = tmp_path / ".commamatrix" / "plugins"
        plugin_root.mkdir(parents=True)
        (plugin_root / "direct_plugin.py").write_text(
            "from commamatrix import tool\n\n"
            "@tool(alias=\"direct\")\n"
            "async def ping() -> str:\n"
            "    return \"pong\"\n",
            encoding="utf-8",
        )
        package = plugin_root / "package_plugin"
        package.mkdir()
        (package / "__init__.py").write_text(
            "from .tools import package_ping\n",
            encoding="utf-8",
        )
        (package / "tools.py").write_text(
            "from commamatrix import tool\n\n"
            "@tool(alias=\"package\")\n"
            "async def package_ping() -> str:\n"
            "    return \"pong\"\n",
            encoding="utf-8",
        )

        monkeypatch.chdir(tmp_path)
        agent = Agent(config={}, auto_load_main=False)
        assert "direct_plugin" in agent.extension_scope
        assert "package_plugin" in agent.extension_scope
        await agent.start()
        try:
            assert "direct_plugin" in agent.extension_scope
            assert "package_plugin" in agent.extension_scope
            assert agent.tool_manager.resolve("direct_ping") is not None
            assert agent.tool_manager.resolve("package_package_ping") is not None
        finally:
            await agent.stop()

    @pytest.mark.asyncio
    async def test_auto_load_plugins_can_be_disabled(self, tmp_path, monkeypatch):
        plugin_root = tmp_path / ".commamatrix" / "plugins"
        plugin_root.mkdir(parents=True)
        (plugin_root / "disabled_plugin.py").write_text(
            "from commamatrix import tool\n\n"
            "@tool(alias=\"disabled\")\n"
            "async def ping() -> str:\n"
            "    return \"pong\"\n",
            encoding="utf-8",
        )

        monkeypatch.chdir(tmp_path)
        agent = Agent(
            config={},
            auto_load_main=False,
            auto_load_plugins=False,
        )
        await agent.start()
        try:
            assert not any(
                name.startswith("direct_plugin")
                for name in agent.extension_scope
            )
            assert agent.tool_manager.resolve("disabled_ping") is None
        finally:
            await agent.stop()

    @pytest.mark.asyncio
    async def test_auto_load_plugins_creates_plugins_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        agent = Agent(config={}, auto_load_main=False)
        await agent.start()
        try:
            assert (tmp_path / ".commamatrix" / "plugins").is_dir()
        finally:
            await agent.stop()

    @pytest.mark.asyncio
    async def test_auto_load_plugins_disabled_skips_plugins_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        agent = Agent(
            config={},
            auto_load_main=False,
            auto_load_plugins=False,
        )
        await agent.start()
        try:
            assert not (tmp_path / ".commamatrix" / "plugins").exists()
        finally:
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
        from commamatrix.components.llm_adapter import (
            LLMResponse,
            StopReason,
            LLMResponseError,
        )

        agent = Agent(config={}, auto_load_main=False)
        resp = LLMResponse(stop_reason=StopReason.ERROR)
        with pytest.raises(LLMResponseError):
            agent._validate_response(resp, None)

    def test_length_stop_raises(self):
        from commamatrix.components.llm_adapter import (
            LLMResponse,
            StopReason,
            LLMTruncatedError,
        )

        agent = Agent(config={}, auto_load_main=False)
        resp = LLMResponse(stop_reason=StopReason.LENGTH)
        with pytest.raises(LLMTruncatedError):
            agent._validate_response(resp, None)

    def test_end_turn_ok(self):
        from commamatrix.components.llm_adapter import LLMResponse, StopReason

        agent = Agent(config={}, auto_load_main=False)
        resp = LLMResponse(stop_reason=StopReason.END_TURN)
        agent._validate_response(resp, None)
