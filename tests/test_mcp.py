# tests/test_mcp.py

from __future__ import annotations

import json
import weakref
from pathlib import Path
from types import SimpleNamespace

import pytest

from commamatrix.builtin.mcp.config import MCPServerSpec, mcp_config_path
from commamatrix.builtin.mcp.hooks import refresh_mcp_config_after_filesystem_tool
from commamatrix.builtin.mcp.instructions import mcp_config_context
from commamatrix.builtin.mcp.loader import MCPConfigLoader, MCPJsonConfigLoader
from commamatrix.builtin.mcp.manager import MCPService
from commamatrix.builtin.mcp.server import MCPServerDescriptor, MCPServerSource
from commamatrix.components.config import Config
from commamatrix.components.hook import AfterToolCallCtx
from commamatrix.components.instruction import InstructionCtx


def _agent(path: Path) -> SimpleNamespace:
    return SimpleNamespace(config=Config({mcp_config_path: str(path)}))


def _spec(server_id: str = "demo") -> MCPServerSpec:
    return MCPServerSpec(
        server_id=server_id,
        transport="stdio",
        command="demo-server",
    )


class StaticLoader(MCPConfigLoader):
    def __init__(self, *specs: MCPServerSpec) -> None:
        self.specs = list(specs)

    def load(self, agent) -> list[MCPServerSpec]:
        return list(self.specs)


class TestMCPJsonConfigLoader:
    def test_loads_host_style_configuration(self, tmp_path: Path):
        path = tmp_path / "mcp.json"
        path.write_text(
            '{"mcpServers": {"demo": {"command": "demo-server", "args": ["--stdio"]}}}',
            encoding="utf-8",
        )

        loader = MCPJsonConfigLoader()
        specs = loader.load(_agent(path))

        assert specs == [
            MCPServerSpec(
                server_id="demo",
                transport="stdio",
                command="demo-server",
                args=("--stdio",),
            )
        ]

    def test_fingerprint_changes_when_file_changes(self, tmp_path: Path):
        path = tmp_path / "mcp.json"
        path.write_text('{"mcpServers": {}}', encoding="utf-8")
        loader = MCPJsonConfigLoader()
        agent = _agent(path)

        first = loader.fingerprint(agent)
        path.write_text(
            '{"mcpServers": {"demo": {"command": "demo-server"}}}',
            encoding="utf-8",
        )

        assert loader.fingerprint(agent) != first

    def test_missing_file_is_empty(self, tmp_path: Path):
        path = tmp_path / "missing.json"
        loader = MCPJsonConfigLoader()

        assert loader.load(_agent(path)) == []

    def test_mcp_service_creates_default_file(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        agent = SimpleNamespace(config=Config(), services=SimpleNamespace())

        MCPService(agent)

        path = tmp_path / ".commamatrix" / "mcp.json"
        assert json.loads(path.read_text(encoding="utf-8")) == {"mcpServers": {}}

    def test_mcp_service_preserves_existing_file(self, tmp_path: Path):
        path = tmp_path / "mcp.json"
        original = '{"mcpServers": {"demo": {"command": "demo-server"}}}'
        path.write_text(original, encoding="utf-8")
        agent = SimpleNamespace(
            config=Config({mcp_config_path: str(path)}),
            services=SimpleNamespace(),
        )

        MCPService(agent)

        assert path.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_custom_loader_can_be_added_to_mcp_service(tmp_path: Path):
    agent = _agent(tmp_path / "mcp.json")
    agent.services = SimpleNamespace()
    service = MCPService(agent)

    await service.add_loader(StaticLoader(_spec("custom")))

    assert [spec.server_id for spec in service._load_specs()] == ["custom"]


class TestMCPServerDescriptors:
    def test_descriptor_fingerprint_contains_spec(self):
        service = SimpleNamespace(_load_specs=lambda: [_spec()])
        source = MCPServerSource(service)
        descriptor = source.scan()[0]

        changed = MCPServerDescriptor(
            id=descriptor.id,
            spec=_spec("changed"),
            _source_ref=weakref.ref(source),
        )

        assert descriptor.id == "mcp-server://demo"
        assert descriptor.fingerprint != changed.fingerprint

    def test_source_rejects_duplicate_server_ids(self):
        service = SimpleNamespace(_load_specs=lambda: [_spec(), _spec()])

        with pytest.raises(ValueError, match="Duplicate MCP server ID"):
            MCPServerSource(service).scan()


@pytest.mark.asyncio
async def test_mcp_hook_refreshes_only_with_filesystem_capability():
    calls: list[str] = []

    class Service:
        async def refresh_if_changed(self) -> bool:
            calls.append("refresh")
            return True

    service = Service()
    agent = SimpleNamespace(
        services=SimpleNamespace(get=lambda service_cls: service),
        tool_manager=SimpleNamespace(
            descriptors=[SimpleNamespace(meta={"filesystem": True})]
        ),
    )
    ctx = AfterToolCallCtx(
        run=SimpleNamespace(agent=agent),
        tool_call=SimpleNamespace(),
        result=SimpleNamespace(),
    )

    await refresh_mcp_config_after_filesystem_tool(ctx)

    assert calls == ["refresh"]


@pytest.mark.asyncio
async def test_mcp_hook_skips_without_filesystem_capability():
    calls: list[str] = []

    class Service:
        async def refresh_if_changed(self) -> bool:
            calls.append("refresh")
            return True

    agent = SimpleNamespace(
        services=SimpleNamespace(get=lambda service_cls: Service()),
        tool_manager=SimpleNamespace(descriptors=[SimpleNamespace(meta={})]),
    )
    ctx = AfterToolCallCtx(
        run=SimpleNamespace(agent=agent),
        tool_call=SimpleNamespace(),
        result=SimpleNamespace(),
    )

    await refresh_mcp_config_after_filesystem_tool(ctx)

    assert calls == []


def test_mcp_instruction_is_conditional_on_filesystem_tools():
    path = Path("mcp.json")
    service = SimpleNamespace(config_paths=(path,))
    agent = SimpleNamespace(
        services=SimpleNamespace(get=lambda service_cls: service),
        tool_manager=SimpleNamespace(
            descriptors=[SimpleNamespace(meta={"filesystem": True})]
        ),
    )

    result = mcp_config_context(InstructionCtx(run=SimpleNamespace(agent=agent)))

    assert result is not None
    assert "mcp.json" in result


def test_mcp_instruction_is_empty_without_filesystem_tools():
    service = SimpleNamespace(config_paths=(Path("mcp.json"),))
    agent = SimpleNamespace(
        services=SimpleNamespace(get=lambda service_cls: service),
        tool_manager=SimpleNamespace(descriptors=[SimpleNamespace(meta={})]),
    )

    assert mcp_config_context(InstructionCtx(run=SimpleNamespace(agent=agent))) is None
