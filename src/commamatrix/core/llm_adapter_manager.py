# core/llm_adapter_manager.py

from __future__ import annotations

from typing import Any

from .service import ManagedServiceManager
from ..api.llm_adapter import LLM_ADAPTER_ATTRIBUTE, LLMAdapter
from ..builtin.python.provider_source import PythonProviderSource


class LLMAdapterManager(ManagedServiceManager):
    """Manages LLMAdapter instances.

    Forwards ask_llm to the first adapter in discovery order.
    """

    def __init__(self) -> None:
        source = PythonProviderSource(LLMAdapter, LLM_ADAPTER_ATTRIBUTE, "llm_adapter")
        super().__init__(source)

    @property
    def _active(self) -> Any | None:
        instances = self.instances
        return instances[0] if instances else None

    async def ask_llm(self, ctx: Any) -> Any:
        adapter = self._active
        if adapter is None:
            raise RuntimeError("No LLM adapters registered")
        return await adapter.ask_llm(ctx)
