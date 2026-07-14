# core/llm_adapter_manager.py

from __future__ import annotations

from typing import Any

from .service_manager import ServiceInstanceManager, ServiceRegistry
from ..api.llm_adapter import LLM_ADAPTER_ATTRIBUTE, LLMAdapter
from ..builtin.python.provider_source import PythonProviderSource


class LLMAdapterManager(ServiceInstanceManager):
    """Manages LLMAdapter instances.

    Forwards ask_llm to the first adapter in discovery order.
    """

    def __init__(self, config: Any, registry: ServiceRegistry) -> None:
        source = PythonProviderSource(LLMAdapter, LLM_ADAPTER_ATTRIBUTE, "llm_adapter")
        super().__init__(source, config, registry)

    @property
    def _active(self) -> LLMAdapter:
        instances = self.instances
        if instances:
            return instances[0]
        raise RuntimeError("No LLM adapters registered")

    async def ask_llm(self, ctx: Any) -> Any:
        return await self._active.ask_llm(ctx)
