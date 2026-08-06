# core/agent/runner.py

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from ...components.dialog import DialogOrigin


class AgentRunner:
    """Manages async runs by namespace and dialog identity."""

    def __init__(self, logger: Any = None) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._logger = logger

    @staticmethod
    def make_key(origin: DialogOrigin, user: str, *, namespace: str = "interactive") -> str:
        return json.dumps(
            {
                'namespace': namespace,
                'origin': origin.model_dump(mode='json'),
                'user': user,
            },
            sort_keys=True, separators=(',', ':'),
        )

    async def submit(self, key: str, coro, *, conflict_policy: Literal["replace", "skip"] = "replace") -> asyncio.Task | None:
        if conflict_policy not in {"replace", "skip"}:
            if hasattr(coro, "close"):
                coro.close()
            raise ValueError(f"Unsupported runner conflict policy: {conflict_policy}")

        active_task = self._tasks.get(key)
        if conflict_policy == "skip" and active_task is not None and not active_task.done():
            if hasattr(coro, "close"):
                coro.close()
            if self._logger is not None:
                self._logger.warning("Run skipped because an active run already exists")
            return None

        old_task = self._tasks.pop(key, None)
        new_task = asyncio.create_task(coro)
        self._tasks[key] = new_task
        if self._logger is not None:
            self._logger.debug("Run task submitted policy=%s active_tasks=%d", conflict_policy, len(self._tasks))

        new_task.add_done_callback(
            lambda t: self._tasks.pop(key, None) if self._tasks.get(key) is t else None
        )

        if old_task and not old_task.done():
            if self._logger is not None:
                self._logger.debug("Replacing active run")
            old_task.cancel()
            try:
                await old_task
            except (asyncio.CancelledError, Exception):
                pass

        return new_task

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        if self._logger is not None and tasks:
            self._logger.info("Stopping run tasks count=%d", len(tasks))
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
