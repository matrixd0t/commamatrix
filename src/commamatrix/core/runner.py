# core/runner.py

import asyncio

from ..api import DialogOrigin


class AgentRunner:
    _tasks: dict[str, asyncio.Task] = {}

    @staticmethod
    def make_key(origin: DialogOrigin, user: str) -> str:
        return ':'.join([str(v) for v in origin.model_dump().values()] + [user])

    @classmethod
    async def submit(cls, key: str, coro) -> None:
        old_task = cls._tasks.pop(key, None)
        new_task = asyncio.create_task(coro)
        cls._tasks[key] = new_task
        new_task.add_done_callback(
            lambda t: cls._tasks.pop(key, None) if cls._tasks.get(key) is t else None
        )

        if old_task and not old_task.done():
            old_task.cancel()
            try:
                await old_task
            except (asyncio.CancelledError, Exception):
                pass
