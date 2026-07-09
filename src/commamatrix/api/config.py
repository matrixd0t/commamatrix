from __future__ import annotations

import sys
from typing import Generic, TypeVar, get_origin, get_args

T = TypeVar('T')


class ConfigField(Generic[T]):
    """A typed configuration field with global state.

    Declare at module level, then read/write via .get()/.set() from anywhere.
    The Agent and built-in plugins read their config through these fields.

    api_key = ConfigField[str](init=True, description="API key")

    api_key.set("sk-...")     # at app startup
    key = api_key.get()       # inside the module
    """

    _FIELD_REGISTRY: list[ConfigField] = []

    def __class_getitem__(cls, item):
        def factory(*args, **kwargs):
            obj = cls.__new__(cls)
            obj._type_hint = item
            obj.__init__(*args, **kwargs)
            return obj
        return factory

    def __init__(self, default: T | None = None, *, init: bool = False, description: str = '') -> None:
        self._default = default
        self._init = init
        self._description = description
        self._value: T | None = None
        self._name: str | None = None

        self._FIELD_REGISTRY.append(self)

    def get(self) -> T:
        """Return the current value, or the default if none was set."""
        if self._value is not None:
            return self._value
        return self._default

    def set(self, value: T) -> None:
        """Persist a value. Overwrites any previously set value."""
        self._value = value

    @classmethod
    def _resolve_names(cls) -> None:
        for field in cls._FIELD_REGISTRY:
            if field._name is not None:
                continue
            for mod in tuple(sys.modules.values()):
                for name, obj in vars(mod).items():
                    if obj is field:
                        field._name = name
                        break

    @classmethod
    def _validate(cls) -> str | None:
        for field in cls._FIELD_REGISTRY:
            if field._init and field._value is None and field._default is None:
                return cls.config_info()
        return None

    @classmethod
    def config_info(cls) -> str:
        """Return a table of all ConfigField's with init=True that need to be set before startup."""
        cls._resolve_names()
        lines: list[str] = []
        for field in cls._FIELD_REGISTRY:
            if not field._init:
                continue
            val = field._value if field._value is not None else field._default
            if field._value is not None:
                hint = 'SET'
            elif field._default is not None:
                hint = 'DEFAULT'
            else:
                hint = 'MISSING'
            lines.append(f'  [{hint}] {field._name or "?"}')
            if val is not None:
                type_str = val.__name__ if isinstance(val, type) else type(val).__name__
            else:
                type_str = _pretty_type(getattr(field, '_type_hint', '?'))
            lines.append(f'         type    : {type_str}')
            lines.append(f'         default : {field._default!r}')
            if field._description:
                lines.append(f'         desc    : {field._description}')
            lines.append('')
        return '\n'.join(lines)


def _pretty_type(t: object) -> str:
    origin = get_origin(t)
    args = get_args(t)
    if origin is type and args:
        inner = args[0]
        return inner.__name__ if isinstance(inner, type) else str(inner)
    if isinstance(t, type):
        return t.__name__
    return str(t)
