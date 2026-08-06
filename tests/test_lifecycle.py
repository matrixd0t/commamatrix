# tests/test_lifecycle.py

"""Tests for AgentLifecycle: start, stop, refresh, set_scope, transactional rollback."""

from __future__ import annotations

import sys
import types

import pytest

from commamatrix.core.classes.manager import Manager, ServiceInstanceManager, ServiceInstanceRegistry
from commamatrix.core.classes.service import AbstractService
from commamatrix.core.agent.lifecycle import AgentLifecycle
from tests.conftest import stub_agent


class TestAgentLifecycleStart:
    def test_logger_reuses_agent_logger_without_creating_another(self, monkeypatch):
        existing_logger = object()
        agent = stub_agent()
        agent.logger = existing_logger
        lifecycle = AgentLifecycle(agent=agent)

        monkeypatch.setattr(
            "commamatrix.core.agent.lifecycle.get_agent_logger",
            lambda *_args: pytest.fail("unexpected logger creation"),
        )

        assert lifecycle.logger is existing_logger

    @pytest.mark.asyncio
    async def test_start_sets_started(self):
        agent = stub_agent()
        children = []
        lifecycle = AgentLifecycle(children=children, registry=agent.services)
        await lifecycle.start()
        assert lifecycle._started is True

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self):
        agent = stub_agent()
        lifecycle = AgentLifecycle(children=[], registry=agent.services)
        await lifecycle.start()
        await lifecycle.start()
        assert lifecycle._started is True

    @pytest.mark.asyncio
    async def test_start_rollback_on_failure(self):
        class FailingManager(Manager):
            async def start(self):
                raise RuntimeError("boom")

        agent = stub_agent()
        mgr = FailingManager(agent)
        lifecycle = AgentLifecycle(children=[mgr], registry=agent.services)
        with pytest.raises(RuntimeError, match="boom"):
            await lifecycle.start()
        assert lifecycle._started is False


class TestAgentLifecycleStop:
    @pytest.mark.asyncio
    async def test_stop_clears_registry(self):
        agent = stub_agent()
        agent.services[str] = object()
        lifecycle = AgentLifecycle(children=[], registry=agent.services)
        await lifecycle.start()
        await lifecycle.stop()
        assert str not in agent.services

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self):
        agent = stub_agent()
        lifecycle = AgentLifecycle(children=[], registry=agent.services)
        await lifecycle.stop()


class TestAgentLifecycleRefresh:
    @pytest.mark.asyncio
    async def test_refresh_skips_when_no_change(self):
        refresh_count = []

        class CountingManager(Manager):
            async def refresh(self):
                refresh_count.append(1)

        agent = stub_agent()
        mgr = CountingManager(agent)
        lifecycle = AgentLifecycle(children=[mgr], registry=agent.services)
        await lifecycle.start()
        refresh_count.clear()
        await lifecycle.refresh()
        assert refresh_count == []

    @pytest.mark.asyncio
    async def test_refresh_runs_when_changed(self):
        refresh_count = []

        class CountingManager(Manager):
            async def refresh(self):
                refresh_count.append(1)

        agent = stub_agent()
        mgr = CountingManager(agent)
        lifecycle = AgentLifecycle(children=[mgr], registry=agent.services)
        await lifecycle.start()
        refresh_count.clear()
        lifecycle._mark_changed()
        await lifecycle.refresh()
        assert refresh_count == [1]

    @pytest.mark.asyncio
    async def test_force_refresh(self):
        refresh_count = []

        class CountingManager(Manager):
            async def refresh(self):
                refresh_count.append(1)

        agent = stub_agent()
        mgr = CountingManager(agent)
        lifecycle = AgentLifecycle(children=[mgr], registry=agent.services)
        await lifecycle.start()
        refresh_count.clear()
        await lifecycle.refresh(force=True)
        assert refresh_count == [1]


class TestAgentLifecycleSetScope:
    def test_set_scope_propagates(self):
        scopes = []

        class ScopeTrackingManager(Manager):
            def set_scope(self, scope):
                scopes.append(list(scope))

        agent = stub_agent()
        mgr = ScopeTrackingManager(agent)
        lifecycle = AgentLifecycle(children=[mgr], registry=agent.services)
        lifecycle.set_scope(["a", "b"])
        assert scopes == [["a", "b"]]

    def test_set_scope_same_no_duplicate(self):
        scopes = []

        class ScopeTrackingManager(Manager):
            def set_scope(self, scope):
                scopes.append(list(scope))

        agent = stub_agent()
        mgr = ScopeTrackingManager(agent)
        lifecycle = AgentLifecycle(children=[mgr], registry=agent.services)
        lifecycle.set_scope(["a"])
        lifecycle.set_scope(["a"])
        assert len(scopes) == 1

    def test_get_manager(self):
        agent = stub_agent()
        mgr = Manager(agent)
        lifecycle = AgentLifecycle(children=[mgr], registry=agent.services)
        assert lifecycle.get_manager(Manager) is mgr
        assert lifecycle.get_manager(type("Other", (Manager,), {})) is None
