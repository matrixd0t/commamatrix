# components/config.py

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
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
            obj._declaration_module = sys._getframe(1).f_globals.get("__name__")
            obj.__init__(*args, **kwargs)
            return obj

        return factory

    def __init__(self, name: str = "", default: T | None | object = _MISSING, *, description: str = "") -> None:
        self._declaration_module = getattr(self, "_declaration_module", sys._getframe(1).f_globals.get("__name__"))
        self._default = default
        self._description = description
        self._name: str | None = name or None

    def __set_name__(self, owner: type, name: str) -> None:
        """Descriptor protocol: capture attribute name when used as a class variable."""
        if not self._name:
            self._name = name

    @property
    def default(self) -> T | None:
        if self._default is _MISSING:
            return None
        if callable(self._default) and not isinstance(self._default, type):
            return self._default()
        return self._default  # type: ignore[return-value]

    @property
    def has_default(self) -> bool:
        return self._default is not _MISSING

    @property
    def description(self) -> str:
        return self._description

    @property
    def name(self) -> str | None:
        return self._name


DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] [agent=%(agent)s] %(message)s"

log_level = ConfigField[str](
    name="log_level",
    default="INFO",
    description="Minimum log level for this agent",
)
log_format = ConfigField[str](
    name="log_format",
    default=DEFAULT_LOG_FORMAT,
    description="Python logging format string for this agent",
)
log_file = ConfigField[str | None](
    name="log_file",
    default=None,
    description="Optional path for rotating agent logs",
)
log_to_console = ConfigField[bool](
    name="log_to_console",
    default=True,
    description="Write agent logs to the console",
)


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

        agent = Agent(name="main", config={
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


def resolve_log_level(value: object) -> int:
    """Convert a configured level to a logging value without breaking logging."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized == "OFF":
            return logging.CRITICAL + 1
        resolved = getattr(logging, normalized, None)
        if isinstance(resolved, int):
            return resolved
    return logging.INFO


class AgentLogger:
    """Small per-agent facade over the standard library logger."""

    def __init__(self, agent: Any, component: str) -> None:
        self._agent = agent
        self._component = component
        self._logger = logging.getLogger(f"commamatrix.{component}")
        configure_agent_logging(agent)

    def isEnabledFor(self, level: int) -> bool:
        config = getattr(self._agent, "config", None)
        if config is None:
            return level >= logging.INFO
        return level >= resolve_log_level(config.get(log_level))

    def log(self, level: int, message: str, *args: object, **kwargs: object) -> None:
        if not self.isEnabledFor(level):
            return
        extra = dict(kwargs.pop("extra", {}) or {})
        extra.setdefault("agent", getattr(self._agent, "name", "<unnamed>"))
        extra.setdefault("component", self._component)
        extra["_commamatrix_agent_id"] = id(self._agent)
        self._logger.log(level, message, *args, extra=extra, **kwargs)

    def debug(self, message: str, *args: object, **kwargs: object) -> None:
        self.log(logging.DEBUG, message, *args, **kwargs)

    def info(self, message: str, *args: object, **kwargs: object) -> None:
        self.log(logging.INFO, message, *args, **kwargs)

    def warning(self, message: str, *args: object, **kwargs: object) -> None:
        self.log(logging.WARNING, message, *args, **kwargs)

    warn = warning

    def error(self, message: str, *args: object, **kwargs: object) -> None:
        self.log(logging.ERROR, message, *args, **kwargs)

    def exception(self, message: str, *args: object, **kwargs: object) -> None:
        kwargs["exc_info"] = True
        self.error(message, *args, **kwargs)


class _AgentHandlerMixin:
    def _bind_agent(self, agent: Any) -> None:
        self._agent_id = id(agent)
        self._config = agent.config
        self._agent_name = getattr(agent, "name", "<unnamed>")

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "_commamatrix_agent_id", None) != self._agent_id:
            return False
        return record.levelno >= resolve_log_level(self._config.get(log_level))

    def format(self, record: logging.LogRecord) -> str:
        configured = self._config.get(log_format)
        fmt = configured if isinstance(configured, str) and configured.strip() else DEFAULT_LOG_FORMAT
        record.agent = getattr(record, "agent", self._agent_name)
        try:
            return logging.Formatter(fmt).format(record)
        except (KeyError, TypeError, ValueError):
            return logging.Formatter(DEFAULT_LOG_FORMAT).format(record)


class _AgentHandler(_AgentHandlerMixin, logging.StreamHandler):
    def __init__(self, agent: Any) -> None:
        logging.StreamHandler.__init__(self)
        self._bind_agent(agent)


class _AgentFileHandler(_AgentHandlerMixin, logging.handlers.RotatingFileHandler):
    def __init__(self, agent: Any, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        logging.handlers.RotatingFileHandler.__init__(
            self,
            path,
            maxBytes=2 * 1024 * 1024,
            backupCount=1,
            encoding="utf-8",
        )
        self._bind_agent(agent)


def configure_agent_logging(agent: Any) -> None:
    """Attach filtered console and optional rotating file handlers for an agent."""
    if not hasattr(agent, "config"):
        return
    try:
        handlers = getattr(agent, "_commamatrix_log_handlers", None)
        if handlers is not None:
            return
        package_logger = logging.getLogger("commamatrix")
        package_logger.setLevel(logging.DEBUG)
        handlers: list[logging.Handler] = []
        if agent.config.get(log_to_console):
            handlers.append(_AgentHandler(agent))
        configured_path = agent.config.get(log_file)
        if configured_path:
            handlers.append(_AgentFileHandler(agent, configured_path))
        for handler in handlers:
            package_logger.addHandler(handler)
        setattr(agent, "_commamatrix_log_handlers", tuple(handlers))
    except (AttributeError, OSError, TypeError):
        # Lightweight test doubles and frozen host objects can use root logging.
        return


def close_agent_logging(agent: Any) -> None:
    handlers = getattr(agent, "_commamatrix_log_handlers", None)
    if handlers is None:
        handler = getattr(agent, "_commamatrix_log_handler", None)
        handlers = (handler,) if handler is not None else ()
    if not handlers:
        return
    package_logger = logging.getLogger("commamatrix")
    for handler in handlers:
        package_logger.removeHandler(handler)
        handler.close()
    try:
        delattr(agent, "_commamatrix_log_handlers")
    except AttributeError:
        pass


def get_agent_logger(agent: Any, component: str) -> AgentLogger:
    return AgentLogger(agent, component)

