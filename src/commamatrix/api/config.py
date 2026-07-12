# api/config.py

from __future__ import annotations

import inspect
from typing import Any, Generic, TypeVar

from .storage import Storage
from .file_storage import FileStorage
from .llm_adapter import LLMAdapter
from .connector import Connector

T = TypeVar("T")
_MISSING = object()


class ConfigField(Generic[T]):
    """A typed configuration schema field.

    Declare at module level as a schema for a configuration parameter.
    Used as dictionary keys in Agent config.

    A field without a default is intentionally validated lazily. The component
    that reads it owns the resulting runtime configuration error.

    telegram_token = ConfigField[str](description="Bot token")

    agent = Agent(config={telegram_token: "..."})
    """

    def __class_getitem__(cls, item):
        def factory(*args, **kwargs):
            obj = cls.__new__(cls)
            obj._type_hint = item
            obj.__init__(*args, **kwargs)
            return obj

        return factory

    def __init__(
        self, default: T | None | object = _MISSING, *, description: str = ""
    ) -> None:
        self._default = default
        self._description = description
        self._name: str | None = None

        frame = inspect.currentframe()
        if frame is not None:
            frame = frame.f_back
        if frame is not None and frame.f_code.co_name == "factory":
            frame = frame.f_back
        if frame is not None:
            for var_name, var_obj in frame.f_locals.items():
                if var_obj is self:
                    self._name = var_name
                    break
        del frame

    @property
    def default(self) -> T | None:
        return None if self._default is _MISSING else self._default  # type: ignore[return-value]

    @property
    def has_default(self) -> bool:
        return self._default is not _MISSING

    @property
    def description(self) -> str:
        return self._description

    @property
    def name(self) -> str | None:
        return self._name


class Config:
    """Per-agent configuration store.

    Resolves values from overrides first, then agent defaults, then field defaults.
    Plugin fields are not globally validated when a Config is created; missing
    values fail when their owning component calls ``get()``.

    agent = Agent(config={
        storage_class: PostgresStorage,
        postgres_dsn: "postgresql://...",
        telegram_token: "bot-token",
    })
    """

    def __init__(
        self,
        overrides: dict[ConfigField, Any] | None = None,
        defaults: dict[ConfigField, Any] | None = None,
    ) -> None:
        self._overrides: dict[ConfigField, Any] = dict(overrides or {})
        self._defaults: dict[ConfigField, Any] = dict(defaults or {})

    def get(self, field: ConfigField[T]) -> T:
        """Resolve a field or raise when no value was configured."""
        if field in self._overrides:
            value = self._overrides[field]
        elif field in self._defaults:
            value = self._defaults[field]
        elif field.has_default:
            value = field.default
        else:
            value = _MISSING

        if value is not _MISSING and (value is not None or field.has_default):
            return value  # type: ignore[return-value]
        raise RuntimeError(f"Missing configuration field: {field.name or '<unnamed>'}")

    def set(self, field: ConfigField[T], value: T) -> None:
        """Override a field value at runtime."""
        self._overrides[field] = value

    def update_defaults(self, defaults: dict[ConfigField, Any]) -> None:
        """Inject additional defaults (used by Agent for built-in services)."""
        for key, val in defaults.items():
            if key not in self._defaults:
                self._defaults[key] = val


# Builtin config field declarations for Agent services.
# Values without defaults fail when the component first reads them. Components
# own the timing and wording of configuration errors for their plugin.
storage_class = ConfigField[type[Storage]](description="Storage backend class")
file_storage_class = ConfigField[type[FileStorage]](
    description="File storage backend class"
)
llm_adapter_class = ConfigField[type[LLMAdapter]](description="LLM adapter class")
connector_classes = ConfigField[list[type[Connector]] | None](
    default=None, description="Connector classes (None = auto-discover)"
)
