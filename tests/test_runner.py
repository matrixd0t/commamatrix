# tests/test_runner.py

"""Tests for AgentRunner."""

from __future__ import annotations

import asyncio

import pytest

from commamatrix.components.dialog import DialogOrigin
from commamatrix.core.agent.runner import AgentRunner
from tests.conftest import StubOrigin


class TestAgentRunnerMakeKey:
    def test_deterministic(self):
        o = StubOrigin(chat_id="c1")
        k1 = AgentRunner.make_key(o, "user1")
        k2 = AgentRunner.make_key(o, "user1")
        assert k1 == k2

    def test_different_origins_different_keys(self):
        o1 = StubOrigin(chat_id="c1")
        o2 = StubOrigin(chat_id="c2")
        k1 = AgentRunner.make_key(o1, "u")
        k2 = AgentRunner.make_key(o2, "u")
        assert k1 != k2

    def test_different_users_different_keys(self):
        o = StubOrigin(chat_id="c1")
        k1 = AgentRunner.make_key(o, "u1")
        k2 = AgentRunner.make_key(o, "u2")
        assert k1 != k2


class TestAgentRunnerSubmit:
    @pytest.mark.asyncio
    async def test_submit_runs_coroutine(self):
        runner = AgentRunner()
        result = []

        async def work():
            result.append("done")

        task = await runner.submit("key1", work())
        assert isinstance(task, asyncio.Task)
        await asyncio.sleep(0.05)
        assert result == ["done"]
        await runner.stop()

    @pytest.mark.asyncio
    async def test_submit_returns_task(self):
        runner = AgentRunner()

        async def work():
            return 42

        task = await runner.submit("key1", work())
        assert isinstance(task, asyncio.Task)
        assert task is runner._tasks["key1"]
        value = await task
        assert value == 42
        await runner.stop()

    @pytest.mark.asyncio
    async def test_submit_cancels_previous(self):
        runner = AgentRunner()
        cancelled = []

        async def long_work():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        async def short_work():
            return

        await runner.submit("key1", long_work())
        await asyncio.sleep(0.02)
        await runner.submit("key1", short_work())
        await asyncio.sleep(0.05)
        assert len(cancelled) == 1
        await runner.stop()


class TestAgentRunnerStop:
    @pytest.mark.asyncio
    async def test_stop_cancels_all(self):
        runner = AgentRunner()
        cancelled = []

        async def long_work():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        await runner.submit("k1", long_work())
        await runner.submit("k2", long_work())
        await asyncio.sleep(0.02)
        await runner.stop()
        assert len(cancelled) == 2

    @pytest.mark.asyncio
    async def test_stop_empty(self):
        runner = AgentRunner()
        await runner.stop()
