# components/config.py

from __future__ import annotations

from typing import Any, Generic, TypeVar

T = TypeVar("T")
_MISSING = object()


class ConfigField(Generic[T]):
    """Typed configuration schema field.

    Declare at module level as a schema for a configuration parameter.
    Used as dictionary keys in Agent config.

    A field without a default is intentionally validated lazily. The component
    that reads it owns the resulting runtime configuration error.
    """

    def __class_getitem__(cls, item):
        def factory(*args, **kwargs):
            obj = cls.__new__(cls)
            obj._type_hint = item
            obj.__init__(*args, **kwargs)
            return obj

        return factory

    def __init__(self, name: str = "", default: T | None | object = _MISSING, *, description: str = "") -> None:
        self._default = default
        self._description = description
        self._name: str | None = name or None

    def __set_name__(self, owner: type, name: str) -> None:
        """Descriptor protocol: capture attribute name when used as a class variable."""
        if not self._name:
            self._name = name

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
    Plugin fields are not globally validated when a Config is created; missing values fail when their owning component calls get().

    Usage::

        # 1. Declare a field at module level in your component
        from commamatrix.components.config import ConfigField

        api_key = ConfigField[str](name="my_api_key", description="API key for ...")
        timeout = ConfigField[float](name="my_timeout", default=30.0, description="Request timeout")

        # 2. Read from config in your component
        class MyService(Service):
            def __init__(self, agent: Agent) -> None:
                super().__init__(agent)
                self._key = self.config.get(api_key)
                self._timeout = self.config.get(timeout)

        # 3. Set in Agent config (the ConfigField object itself is the key)
        from my_plugin import api_key, timeout

        agent = Agent(config={
            api_key: "sk-...",
            timeout: 60.0,
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
        self._overrides[field] = value

    def update_defaults(self, defaults: dict[ConfigField, Any]) -> None:
        for key, val in defaults.items():
            if key not in self._defaults:
                self._defaults[key] = val

    def has_override(self, field: ConfigField) -> bool:
        return field in self._overrides

    def __contains__(self, field: ConfigField) -> bool:
        return field in self._overrides or field in self._defaults or field.has_default
