# builtin/subagent/submit.py

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from ...components.dialog import DialogItem, DialogItemType, DialogRole
from ...components.hook import AfterLlmCallCtx, RunCtx
from ...components.llm_adapter import StructuredOutputModel
from ...utils import FP
from .policy import validate_allowed_tools
from .service import SubagentService

if TYPE_CHECKING:
    from ...core.agent.agent import Agent


async def submit_run(
    agent: Agent,
    *,
    parent_item_id: int | None = None,
    instructions: str | None = None,
    dialog_items: list[DialogItem] | None = None,
    tools: str | None,
    response_format: StructuredOutputModel | None = None,
    user: str = "agent",
    meta: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    wait_for_result: bool = True,
    conflict_policy: Literal["replace", "skip"] = "skip",
    runner_namespace: str = "subagent",
    runner_key: str | None = None,
    on_error: Callable[[Exception], Any] | None = None,
) -> AfterLlmCallCtx | str | None:
    """Submit a headless run and resolve its result through the internal connector."""
    await agent._ensure_started()
    target = FP + ".builtin.subagent"
    if not any(
        module_name == target or module_name.startswith(target + ".")
        for module_name in agent.extension_scope
    ):
        await agent.add_extensions(target)

    try:
        validate_allowed_tools(tools)
    except Exception as exc:
        if not wait_for_result:
            return f"{type(exc).__name__}: {exc}"
        raise
    try:
        service: SubagentService = agent.services.require(SubagentService)
        task_id = uuid4().hex
        origin = service.make_origin(task_id, parent_item_id)
        connector = service.register(origin, wait_for_result=wait_for_result, on_error=on_error)
    except Exception as exc:
        if not wait_for_result:
            return f"{type(exc).__name__}: {exc}"
        raise

    items = list(dialog_items or [])
    if instructions:
        items.insert(
            0,
            DialogItem(
                content=instructions,
                item_type=DialogItemType.INPUT,
                role=DialogRole.SYSTEM,
                origin=origin,
                user=user,
                previous_item_id=parent_item_id,
            ),
        )

    if not items and parent_item_id is None:
        service.unregister(origin)
        error = ValueError("submit_run requires instructions, dialog_items, or parent_item_id")
        if not wait_for_result:
            return f"{type(error).__name__}: {error}"
        raise error

    for item in items:
        if item.item_id is None:
            item.origin = origin
            item.user = user
    if items:
        first = items[0]
        if first.item_id is None:
            first.previous_item_id = parent_item_id
        if meta:
            first.meta.update(meta)

    run_state = dict(state or {})
    run_state.update({"subagent": True, "allowed_tools": tools})
    run = RunCtx(
        agent=agent,
        connector=connector,
        origin=origin,
        user=user,
        response_format=response_format,
        state=run_state,
        chain_state={"allowed_tools": tools},
        last_item_id=parent_item_id,
    )
    key = runner_key or f"{runner_namespace}:{user}:{parent_item_id}"
    try:
        task = await agent.runner.submit(
            key,
            agent.run(run, history=items or None),
            conflict_policy=conflict_policy,
        )
    except Exception as exc:
        service.unregister(origin)
        if not wait_for_result:
            return f"{type(exc).__name__}: {exc}"
        raise
    if task is None:
        service.unregister(origin)
        return "Subagent run was skipped" if not wait_for_result else None

    async def settle() -> None:
        try:
            result = await task
        except asyncio.CancelledError:
            await service.complete(origin, None, RuntimeError("Subagent run was cancelled"))
            raise
        except Exception as exc:  # noqa: BLE001
            await service.complete(origin, None, exc)
        else:
            await service.complete(origin, result)

    if not wait_for_result:
        asyncio.create_task(settle())
        return "OK"

    waiter = connector.waiter(origin)
    await settle()
    return await waiter


__all__ = ["submit_run"]
