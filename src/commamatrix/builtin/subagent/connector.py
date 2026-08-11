# builtin/subagent/connector.py

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ...components.connector import Connector
from ...components.dialog import DialogItem, DialogItemType, DialogOrigin
from ...components.hook import AfterLlmCallCtx, OnParsedCtx, RunCtx
from ...utils import await_if_needed


class InternalOrigin(DialogOrigin):
    """Origin identifying a headless run and its dialog parent."""

    origin_type: str = "internal"
    platform: str = "internal"
    task_id: str
    parent_item_id: int | None = None


@dataclass(slots=True)
class _PendingRun:
    future: asyncio.Future[AfterLlmCallCtx | None] | None
    on_error: Callable[[Exception], Any] | None


class InternalConnector(Connector[InternalOrigin]):
    """Bridges a headless run back to the code that submitted it."""

    def __init__(self, agent) -> None:
        super().__init__(agent)
        self._items: dict[str, list[DialogItem]] = {}
        self._pending: dict[str, _PendingRun] = {}

    async def parse(self, data: dict) -> OnParsedCtx | None:
        return None

    async def send(self, run: RunCtx, item: DialogItem) -> str:
        if item.item_type != DialogItemType.OUTPUT:
            return ""
        internal_origin = self._as_internal(run.origin)
        self._items.setdefault(internal_origin.task_id, []).append(item)
        return ""

    def register(self, origin: InternalOrigin, *, wait_for_result: bool, on_error: Callable[[Exception], Any] | None = None) -> None:
        future = asyncio.get_running_loop().create_future() if wait_for_result else None
        self._pending[origin.task_id] = _PendingRun(future=future, on_error=on_error)

    def waiter(self, origin: InternalOrigin) -> asyncio.Future[AfterLlmCallCtx | None]:
        request = self._pending.get(origin.task_id)
        if request is None or request.future is None:
            raise RuntimeError("This internal run does not wait for a result")
        return request.future

    def unregister(self, origin: InternalOrigin) -> None:
        self._pending.pop(origin.task_id, None)
        self._items.pop(origin.task_id, None)

    async def complete(self, origin: InternalOrigin, result: AfterLlmCallCtx | None, error: Exception | None = None) -> None:
        task_id = origin.task_id
        items = self._items.pop(task_id, [])
        response = "\n\n".join(item.content for item in items)
        pending = self._pending.pop(task_id, None)

        if result is not None:
            result.meta["internal_response"] = response

        if pending is None:
            return

        if error is not None:
            if pending.future is not None and not pending.future.done():
                pending.future.set_exception(error)
            if pending.on_error is not None:
                await await_if_needed(pending.on_error(error))
            return

        if pending.future is not None and not pending.future.done():
            pending.future.set_result(result)

    async def stop(self) -> None:
        pending = tuple(self._pending.items())
        self._pending.clear()
        self._items.clear()
        error = RuntimeError("Internal run connector stopped")
        for _, request in pending:
            if request.future is not None and not request.future.done():
                request.future.set_exception(error)
            if request.on_error is not None:
                await await_if_needed(request.on_error(error))
        await super().stop()

    @staticmethod
    def _as_internal(origin: DialogOrigin) -> InternalOrigin:
        if not isinstance(origin, InternalOrigin):
            raise TypeError(f"InternalConnector cannot handle {type(origin).__name__}")
        return origin


__all__ = ["InternalConnector", "InternalOrigin"]

