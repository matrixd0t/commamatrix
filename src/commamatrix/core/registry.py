from collections.abc import Collection, Iterator
from dataclasses import dataclass, field
from typing import Any, Awaitable, Self, cast, Callable

type AsyncOrSyncFunction = Callable[..., object] | Callable[..., Awaitable[object]]


@dataclass(frozen=True)
class FunctionRegistryEntry:
    fn: AsyncOrSyncFunction
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.fn.__name__

    def __getattr__(self, name: str) -> Any:
        # fn и meta находятся через обычный __getattribute__, сюда попадают только обращения к полям meta
        try:
            return self.meta[name]
        except KeyError:
            raise AttributeError(f'FunctionRegistryEntry has no attribute {name!r}')

    def get(self, key: str, default: Any = None) -> Any:
        return self.meta.get(key, default)


class FunctionRegistry(Collection[FunctionRegistryEntry]):
    """
    Универсальный реестр функций.
    """

    def __init__(self) -> None:
        self._entries: list[FunctionRegistryEntry] = []

    def __contains__(self, x: object) -> bool:
        return x in self._entries

    def __iter__(self) -> Iterator[FunctionRegistryEntry]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def register(self, fn: Callable[..., Any], **meta: Any) -> FunctionRegistryEntry:
        entry = FunctionRegistryEntry(fn=fn, meta=meta)
        self._entries.append(entry)
        return entry

    def where(self, predicate: Callable[[FunctionRegistryEntry], bool] | None = None, **attrs: Any) -> Self:
        def matches(e: FunctionRegistryEntry) -> bool:
            if predicate is not None and not predicate(e):
                return False
            return all(e.meta.get(k) == v for k, v in attrs.items())

        new = self.copy()
        new._entries = [e for e in self._entries if matches(e)]
        return new

    def copy(self) -> Self:
        cls = cast(type[Self], type(self))
        new = cls.__new__(cls)
        new._entries = list(self._entries)
        return new

    def __copy__(self) -> Self:
        return self.copy()
