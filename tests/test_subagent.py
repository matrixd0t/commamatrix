# tests/test_subagent.py

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from commamatrix import InstructionCtx
from commamatrix.builtin.subagent import hooks
from commamatrix.builtin.subagent import tools as subagent_tools
import commamatrix.builtin.subagent.submit as submit_module
from commamatrix.components.dialog import DialogItem, DialogItemType, DialogRole
from commamatrix.components.hook import BeforeToolCallCtx, RunCtx
from commamatrix.components.llm_adapter import ToolCall
from commamatrix.core.agent.agent import Agent, agent_by_name, get_subagent_by_name
from tests.conftest import stub_origin


class _TargetAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def submit_run(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "started"


@pytest.mark.asyncio
async def test_call_subagent_uses_named_agent(monkeypatch):
    target = _TargetAgent()
    monkeypatch.setattr(subagent_tools, "get_subagent_by_name", lambda name: target)

    result = await subagent_tools.call_subagent(
        "executor",
        instructions="do the work",
        tools="all",
        wait_for_result=False,
    )

    assert result == "started"
    assert target.calls == [
        {
            "parent_item_id": None,
            "instructions": "do the work",
            "tools": "all",
            "wait_for_result": False,
            "user": "agent",
        }
    ]


@pytest.mark.asyncio
async def test_prepare_subagent_call_passes_parent_item_id():
    descriptor = SimpleNamespace(alias="subagent", name="call_subagent")
    agent = SimpleNamespace(
        name="parent",
        tool_manager=SimpleNamespace(resolve=lambda name: descriptor),
    )
    run = RunCtx(
        agent=agent,
        origin=stub_origin(),
        user="agent",
        state={"child_parent_item_id": 42},
    )
    ctx = BeforeToolCallCtx(
        run=run,
        tool_call=ToolCall(
            tool_call_id="call-1",
            tool_name="subagent_call_subagent",
            tool_args={"continue_from_here": True, "parent_item_id": 999},
        ),
    )

    await hooks.prepare_subagent_call(ctx)

    assert ctx.tool_call.tool_args["subagent"] == "parent"
    assert ctx.tool_call.tool_args["parent_item_id"] == 42


@pytest.mark.asyncio
async def test_prepare_subagent_call_rejects_missing_parent_item_id():
    descriptor = SimpleNamespace(alias="subagent", name="call_subagent")
    agent = SimpleNamespace(
        name="parent",
        tool_manager=SimpleNamespace(resolve=lambda name: descriptor),
    )
    run = RunCtx(agent=agent, origin=stub_origin(), user="agent")
    ctx = BeforeToolCallCtx(
        run=run,
        tool_call=ToolCall(
            tool_call_id="call-1",
            tool_name="subagent_call_subagent",
            tool_args={"continue_from_here": True},
        ),
    )

    with pytest.raises(ValueError, match="persisted parent item"):
        await hooks.prepare_subagent_call(ctx)


@pytest.mark.asyncio
async def test_submit_run_orders_instructions_prompt_and_dialog_items(monkeypatch):
    target = submit_module.FP + ".builtin.subagent"
    captured: dict[str, Any] = {}
    result = object()

    class _Connector:
        def __init__(self) -> None:
            self.future = asyncio.get_running_loop().create_future()

        def waiter(self, _origin):
            return self.future

    connector = _Connector()

    class _Service:
        def make_origin(self, task_id, parent_item_id):
            return stub_origin(task_id)

        def register(self, origin, *, wait_for_result, on_error=None):
            return connector

        async def complete(self, origin, completed, error=None):
            connector.future.set_result(completed)

        def unregister(self, origin):
            pass

    class _Runner:
        async def submit(self, key, coroutine, *, conflict_policy):
            return asyncio.create_task(coroutine)

    class _Agent:
        extension_scope = (target,)
        services = SimpleNamespace(require=lambda _service_type: _Service())
        runner = _Runner()

        async def _ensure_started(self):
            pass

        async def add_extensions(self, _target):
            pass

        async def run(self, run, *, history):
            captured["run"] = run
            captured["history"] = history
            return result

    monkeypatch.setattr(submit_module, "validate_allowed_tools", lambda tools: None)

    returned = await submit_module.submit_run(
        _Agent(),
        instructions="system",
        prompt="user",
        dialog_items=[DialogItem(content="context", item_type=DialogItemType.INPUT, role=DialogRole.USER, origin=stub_origin())],
        tools=None,
    )

    assert returned is result
    assert [item.content for item in captured["history"]] == ["system", "user", "context"]
    assert captured["history"][0].role is DialogRole.SYSTEM
    assert captured["history"][1].role is DialogRole.USER
    assert captured["run"].save is True
    assert captured["run"].aggregate_instructions is True


def test_agent_name_is_registered():
    name = "registry-test-agent"
    name2 = "registry-test-agent2"
    agent = Agent(name, auto_load_main=False, auto_load_plugins=False)
    agent2 = Agent(name2, auto_load_main=False, auto_load_plugins=False)
    try:
        assert agent_by_name[name] is agent
        assert get_subagent_by_name(name) is agent

        agent.name = "renamed-registry-test-agent"
        agent.description = "updated description"
        with pytest.raises(KeyError):
            get_subagent_by_name(name)
        assert get_subagent_by_name(agent.name) is agent
        assert "updated description" in hooks.available_subagents(InstructionCtx(run=RunCtx(agent=agent2, origin=stub_origin(), user="user")))
    finally:
        agent_by_name.pop(agent.name, None)
