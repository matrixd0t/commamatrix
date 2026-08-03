# builtin/subagent/service.py

from __future__ import annotations

from typing import Any, Callable, TYPE_CHECKING

from ...components.hook import AfterLlmCallCtx
from ...core.classes.service import Service
from .connector import InternalConnector, InternalOrigin

if TYPE_CHECKING:
    from ...core.agent.agent import Agent


class SubagentService(Service):
    """Owns the internal transport used by headless agent runs."""

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)

    def make_origin(self, task_id: str, parent_item_id: int | None) -> InternalOrigin:
        return InternalOrigin(task_id=task_id, parent_item_id=parent_item_id)

    def connector_for(self, origin: InternalOrigin) -> InternalConnector:
        connector = self.agent.connector_manager.resolve_for_origin(origin)
        if not isinstance(connector, InternalConnector):
            raise TypeError(f"Expected InternalConnector for {origin!r}, found {type(connector).__name__}")
        return connector

    def register(self, origin: InternalOrigin, *, wait_for_result: bool, on_error: Callable[[Exception], Any] | None = None) -> InternalConnector:
        connector = self.connector_for(origin)
        connector.register(origin, wait_for_result=wait_for_result, on_error=on_error,)
        return connector

    async def complete(self, origin: InternalOrigin, result: AfterLlmCallCtx | None, error: Exception | None = None) -> None:
        await self.connector_for(origin).complete(origin, result, error)

    def unregister(self, origin: InternalOrigin) -> None:
        self.connector_for(origin).unregister(origin)


__all__ = ["SubagentService"]
