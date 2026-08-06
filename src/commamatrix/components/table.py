# components/table.py

from __future__ import annotations

import re
import weakref
from abc import ABC
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, Protocol, TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from ..core.classes.descriptor import Descriptor
from ..core.classes.lifecycle_registry import lifecycle_component
from ..core.classes.manager import Manager
from ..core.classes.source import PythonSource

if TYPE_CHECKING:
    from ..core.agent.agent import Agent


TABLE_ATTRIBUTE = "__commamatrix_table__"
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

RowT = TypeVar("RowT", bound=BaseModel)


class BaseTable(Generic[RowT], ABC):
    """Declarative table owned by an extension.

    ``row_model`` describes one stored row. The table itself is discovered by
    ``TableManager`` and applied to the active storage backend.
    """

    table_id: ClassVar[str] = ""
    table_name: ClassVar[str] = ""
    row_model: ClassVar[type[BaseModel]]
    primary_key: ClassVar[str | None] = None
    auto_increment: ClassVar[str | None] = None
    indexes: ClassVar[tuple[tuple[str, ...], ...]] = ()
    unique_indexes: ClassVar[tuple[tuple[str, ...], ...]] = ()
    version: ClassVar[int] = 1

    @classmethod
    def resolved_table_id(cls) -> str:
        if cls.table_id.strip():
            return cls.table_id
        return f"{cls.__module__}.{cls.__qualname__}"

    @classmethod
    async def migrate(cls, backend: SchemaBackend, from_version: int) -> None:
        raise RuntimeError(
            f"Table {cls.__module__}.{cls.__qualname__} does not define a migration "
            f"from version {from_version} to {cls.version}"
        )

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if cls is BaseTable:
            return
        if getattr(cls, "table_name", "") and getattr(cls, "row_model", None) is not None:
            setattr(cls, TABLE_ATTRIBUTE, True)


@dataclass(frozen=True, slots=True)
class TableDescriptor(Descriptor):
    """Immutable metadata for a discovered plugin table."""
    table_cls: type[BaseTable]

    def _fingerprint_payload(self) -> dict[str, Any]:
        table_cls = self.table_cls
        return {
            "id": self.id,
            "table_cls": f"{table_cls.__module__}.{table_cls.__qualname__}",
            "table_id": table_cls.resolved_table_id(),
            "table_name": table_cls.table_name,
            "row_model": f"{table_cls.row_model.__module__}.{table_cls.row_model.__qualname__}",
            "row_fields": tuple(table_cls.row_model.model_fields),
            "primary_key": table_cls.primary_key,
            "auto_increment": table_cls.auto_increment,
            "indexes": table_cls.indexes,
            "unique_indexes": table_cls.unique_indexes,
            "version": table_cls.version,
        }


class PythonTableSource(PythonSource[TableDescriptor]):
    """Discover ``BaseTable`` subclasses in the active extension scope."""

    @property
    def marker_attribute(self) -> str:
        return TABLE_ATTRIBUTE

    def build_descriptor(self, object_name: str, obj: object) -> TableDescriptor | None:
        if not isinstance(obj, type) or not issubclass(obj, BaseTable):
            return None

        table_name = getattr(obj, "table_name", "")
        row_model = getattr(obj, "row_model", None)
        if not isinstance(table_name, str) or not _IDENTIFIER_RE.fullmatch(table_name):
            raise ValueError(f"Invalid table name {table_name!r} on {obj.__module__}.{object_name}")
        if not isinstance(row_model, type) or not issubclass(row_model, BaseModel):
            raise TypeError(f"Table {obj.__module__}.{object_name} must define a Pydantic row_model")

        primary_key = getattr(obj, "primary_key", None)
        fields = set(row_model.model_fields)
        if primary_key is not None and primary_key not in fields:
            raise ValueError(f"Primary key {primary_key!r} is not a field of {row_model.__name__}")

        auto_increment = getattr(obj, "auto_increment", None)
        if auto_increment is not None:
            if not isinstance(auto_increment, str) or auto_increment not in fields:
                raise ValueError(f"Autoincrement field {auto_increment!r} is not a field of {row_model.__name__}")
            if primary_key != auto_increment:
                raise ValueError("Autoincrement field must also be the primary key")

        indexes = tuple(tuple(index) for index in getattr(obj, "indexes", ()))
        for index in indexes:
            if not index or any(field_name not in fields for field_name in index):
                raise ValueError(f"Invalid index declaration on {obj.__module__}.{object_name}: {index!r}")

        unique_indexes = tuple(tuple(index) for index in getattr(obj, "unique_indexes", ()))
        for index in unique_indexes:
            if not index or any(field_name not in fields for field_name in index):
                raise ValueError(f"Invalid unique index declaration on {obj.__module__}.{object_name}: {index!r}")

        version = getattr(obj, "version", 1)
        if not isinstance(version, int) or version < 1:
            raise ValueError(f"Table {obj.__module__}.{object_name} must have a positive integer version")

        table_id = getattr(obj, "table_id", "")
        if not isinstance(table_id, str):
            raise ValueError(f"Table {obj.__module__}.{object_name} must define a string table_id")

        return TableDescriptor(
            id=f"table://{obj.__module__}/{object_name}",
            table_cls=obj,
            _source_ref=weakref.ref(self),
        )


class SchemaBackend(Protocol):
    """Storage capability required by ``TableManager`` and table migrations."""

    async def ensure_table(self, table: TableDescriptor) -> None: ...

    async def add_column(self, table_name: str, column_name: str, sql_type: str, *, nullable: bool = True) -> None: ...


@lifecycle_component(key="table_manager", priority=500, after="storage")
class TableManager(Manager[TableDescriptor]):
    """Discovers and applies extension-owned tables to active storage."""

    def __init__(self, agent: Agent, **kwargs: Any) -> None:
        super().__init__(agent, **kwargs)
        self._python_source = PythonTableSource()
        self.mount(self._python_source)

    def set_scope(self, scope: list[str]) -> None:
        self._python_source.set_scope(scope)

    async def refresh(self) -> None:
        await super().refresh()
        await self._ensure_tables()

    async def _ensure_tables(self) -> None:
        tables = tuple(self.descriptors)
        if not tables:
            return

        storage = self.agent.storage.active
        backend = getattr(storage, "schema_backend", None)
        if backend is None:
            raise RuntimeError(
                f"Active storage {type(storage).__name__} does not support plugin tables"
            )

        for table in sorted(tables, key=lambda descriptor: descriptor.table_cls.resolved_table_id()):
            await backend.ensure_table(table)

    def _rebuild(self) -> None:
        by_table_id: dict[str, TableDescriptor] = {}
        by_table_name: dict[str, TableDescriptor] = {}
        for descriptor in self.descriptors:
            table_cls = descriptor.table_cls
            table_id = table_cls.resolved_table_id()
            previous_id = by_table_id.get(table_id)
            if previous_id is not None:
                raise ValueError(
                    f"Duplicate plugin table id {table_id!r}: "
                    f"{previous_id.id} and {descriptor.id}"
                )

            previous_name = by_table_name.get(table_cls.table_name)
            if previous_name is not None:
                raise ValueError(
                    f"Duplicate plugin table name {table_cls.table_name!r}: "
                    f"{previous_name.id} and {descriptor.id}"
                )

            by_table_id[table_id] = descriptor
            by_table_name[table_cls.table_name] = descriptor


__all__ = [
    "TABLE_ATTRIBUTE",
    "BaseTable",
    "TableDescriptor",
    "PythonTableSource",
    "SchemaBackend",
    "TableManager",
]


