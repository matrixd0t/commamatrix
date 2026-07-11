# core/services.py

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


class ServiceRegistry:
    _services: dict[type, object]

    def __init__(self) -> None:
        self._services = {}

    def __setitem__(self, key: type[T], value: T) -> None:
        self._services[key] = value

    def __getitem__(self, key: type[T]) -> T:
        return self._services[key]  # type: ignore[return-value]

    def get(self, key: type[T]) -> T | None:
        return self._services.get(key)  # type: ignore[return-value]

    def require(self, key: type[T]) -> T:
        value = self._services.get(key)
        if value is None:
            raise KeyError(f"Service {key.__name__} not registered")
        return value  # type: ignore[return-value]

    def values(self):
        return self._services.values()

    def __contains__(self, key: type) -> bool:
        return key in self._services
