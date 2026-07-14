# core/provider_manager.py

from __future__ import annotations

from typing import Any

from .service_manager import ServiceInstanceManager, ServiceRegistry
from ..api.config import Config, ConfigField
from ..api.service import AbstractService
from ..builtin.python.provider_source import PythonProviderSource


class ActiveInstanceManager(ServiceInstanceManager):
    """ServiceInstanceManager with active-instance selection.

    Subclasses set class attributes to configure provider discovery
    and active selection:

        _cls          — AbstractService base class (Storage, FileStorage, …)
        _attribute    — __init_subclass__ marker attribute
        _prefix       — id prefix + error message label
        active_field  — ConfigField that controls which instance is active

    Forwarding methods call self._active and delegate to the active instance.
    """

    _cls: type[AbstractService]
    _attribute: str
    _prefix: str = 'provider'
    active_field: ConfigField[str | None]

    def __init__(self, config: Config, registry: ServiceRegistry) -> None:
        source = PythonProviderSource(self._cls, self._attribute, self._prefix)
        super().__init__(source, config, registry)
        self._active_id: str | None = None

    async def refresh(self) -> None:
        await super().refresh()
        self._select_active()

    def _select_active(self) -> None:
        configured = self._config.get(self.active_field)
        if configured is not None:
            if configured in self._instances:
                self._active_id = configured
                return
            if self._config.has_override(self.active_field):
                raise RuntimeError(f"Active {self._prefix} '{configured}' not found")
        if self._active_id is not None and self._active_id in self._instances:
            return
        if self._instances:
            self._active_id = next(iter(self._instances))

    @property
    def _active(self) -> Any | None:
        if self._active_id is None:
            raise RuntimeError(f"No active {self._prefix}")
        return self._instances.get(self._active_id)
