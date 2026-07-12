# core/runner.py

from __future__ import annotations

import asyncio
import json

from ..api import DialogOrigin


class AgentRunner:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    @staticmethod
    def make_key(origin: DialogOrigin, user: str) -> str:
        return json.dumps(
            {'origin': origin.model_dump(mode='json'), 'user': user},
            sort_keys=True, separators=(',', ':'),
        )

    async def submit(self, key: str, coro) -> None:
        old_task = self._tasks.pop(key, None)
        new_task = asyncio.create_task(coro)
        self._tasks[key] = new_task

        new_task.add_done_callback(
            lambda t: self._tasks.pop(key, None) if self._tasks.get(key) is t else None
        )

        if old_task and not old_task.done():
            old_task.cancel()
            try:
                await old_task
            except (asyncio.CancelledError, Exception):
                pass

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
