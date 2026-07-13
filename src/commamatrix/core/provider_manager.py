# core/provider_manager.py

from __future__ import annotations

from typing import Any

from .service import ManagedServiceManager, ServiceRegistry
from ..api.config import Config, ConfigField


class ProviderManager(ManagedServiceManager):
    """ManagedServiceManager with active-provider selection.

    Subclasses define which ConfigField controls the active provider
    and implement forwarding methods for the provider's API.
    """

    active_field: ConfigField[str | None]
    _active_id: str | None
    _override_error_prefix: str = "provider"

    def __init__(self, python_source: Any, active_field: ConfigField[str | None], error_prefix: str) -> None:
        super().__init__(python_source)
        self.active_field = active_field
        self._active_id: str | None = None
        self._override_error_prefix = error_prefix

    async def reconcile(self, config: Config, registry: ServiceRegistry) -> None:
        """Reconcile instances and re-derive active provider from config."""
        await super().reconcile(config, registry)
        self._select_active(config)

    def _select_active(self, config: Config) -> None:
        """Derive the active provider from config on every call."""
        configured = config.get(self.active_field)
        if configured is not None:
            if configured in self._instances:
                self._active_id = configured
                return
            if config.has_override(self.active_field):
                raise RuntimeError(f"Active {self._override_error_prefix} '{configured}' not found")
        if self._active_id is not None and self._active_id in self._instances:
            return
        if self._instances:
            self._active_id = next(iter(self._instances))

    @property
    def _active(self) -> Any | None:
        if self._active_id is None:
            return None
        return self._instances.get(self._active_id)
