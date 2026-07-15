# builtin/sql/storage.py

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from types import UnionType
from typing import Any, Union, get_args, get_origin, TYPE_CHECKING

from ...components.dialog import (
    DialogItem,
    DialogOrigin,
    DialogItemType,
    DialogRole,
    ORIGIN_REGISTRY,
    resolve_origin_type,
)
from ...components.storage import Storage

if TYPE_CHECKING:
    from ...components.config import Config

BaseColumns = set(DialogItem.model_fields.keys()) - {"origin"} | set(
    DialogOrigin.model_fields.keys()
)


def python_type_to_sql(t: type) -> str:
    origin = get_origin(t)
    if origin is Union or origin is UnionType:
        args = [a for a in get_args(t) if a is not type(None)]
        t = args[0] if args else str
    if not isinstance(t, type):
        return "TEXT"
    if issubclass(t, bool):
        return "INTEGER"
    if issubclass(t, int):
        return "INTEGER"
    if issubclass(t, float):
        return "REAL"
    return "TEXT"


def _field_is_nullable(field_info) -> bool:
    ann = field_info.annotation
    if ann is type(None):
        return True
    origin = get_origin(ann)
    if origin is Union or origin is UnionType:
        args = get_args(ann)
        return any(a is type(None) for a in args)
    return False


class SqlStorage(Storage, ABC):
    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self._db: Any = None
        self._known_columns: set[str] = set()

    @abstractmethod
    async def _connect(self) -> Any: ...

    @abstractmethod
    async def _execute(self, db: Any, query: str, params: tuple = ()) -> Any: ...

    @abstractmethod
    async def _fetchall(self, db: Any, query: str, params: tuple = ()) -> list: ...

    @abstractmethod
    async def _insert(self, db: Any, query: str, params: tuple = ()) -> int | None: ...

    @abstractmethod
    async def _commit(self, db: Any) -> None: ...

    @abstractmethod
    async def _close(self) -> None: ...

    @abstractmethod
    async def _columns(self, db: Any) -> set[str]:
        """Return the current column names for the dialog table."""
        ...

    def _placeholder(self, index: int) -> str:
        return "?"

    def _quote_ident(self, name: str) -> str:
        return name

    def _pk_type(self) -> str:
        return "INTEGER PRIMARY KEY AUTOINCREMENT"

    def _insert_returning_suffix(self) -> str:
        return ""

    def _col_sql(self, name: str, field_info) -> str:
        if name == "item_id":
            return f"{self._quote_ident(name)} {self._pk_type()}"
        sql_type = python_type_to_sql(field_info.annotation)
        nullable = _field_is_nullable(field_info)
        null_str = "" if nullable else " NOT NULL"
        return f"{self._quote_ident(name)} {sql_type}{null_str}"

    async def _get_db(self) -> Any:
        if self._db is None:
            self._db = await self._connect()
            await self._init_db()
        return self._db

    async def _init_db(self) -> None:
        db = self._db

        cols = []
        for name, field_info in DialogItem.model_fields.items():
            if name == "origin":
                continue
            cols.append(self._col_sql(name, field_info))
        for name, field_info in DialogOrigin.model_fields.items():
            cols.append(self._col_sql(name, field_info))

        columns_sql = ",\n                ".join(cols)

        await self._execute(
            db,
            f"""
            CREATE TABLE IF NOT EXISTS dialog_items (
                {columns_sql}
            )
        """,
        )
        await self._commit(db)

        self._known_columns = await self._columns(db)

        await self._migrate_columns(DialogItem, skip={"origin"})
        await self._migrate_columns(DialogOrigin)
        for origin_cls in ORIGIN_REGISTRY.values():
            await self._migrate_columns(origin_cls)

    async def _migrate_columns(
        self, model_cls: type, skip: set[str] | None = None
    ) -> None:
        skip = skip or set()
        db = self._db
        for name, field_info in model_cls.model_fields.items():
            if name in skip or name in self._known_columns:
                continue
            sql_type = python_type_to_sql(field_info.annotation)
            try:
                await self._execute(
                    db,
                    f"ALTER TABLE dialog_items ADD COLUMN {self._quote_ident(name)} {sql_type}",
                )
                await self._commit(db)
            except Exception as exc:
                self._known_columns = await self._columns(db)
                if name not in self._known_columns:
                    raise RuntimeError(
                        f"Failed to migrate dialog_items.{name}"
                    ) from exc
            self._known_columns.add(name)

    @staticmethod
    def _origin_to_row(origin: DialogOrigin) -> dict[str, Any]:
        return origin.model_dump(mode="json")

    @staticmethod
    def _row_to_origin(row: Any, origin_cls: type[DialogOrigin]) -> DialogOrigin:
        return origin_cls(**{name: row[name] for name in origin_cls.model_fields})

    @staticmethod
    def _find_origin_class(row: Any) -> type[DialogOrigin]:
        return resolve_origin_type({name: row[name] for name in row.keys()})

    async def save_event(self, entry: DialogItem) -> int | None:
        db = await self._get_db()

        origin_type = type(entry.origin)
        await self._migrate_columns(origin_type)

        origin_row = self._origin_to_row(entry.origin)

        data = entry.model_dump(mode="json")
        data.pop("item_id")
        data.pop("origin")
        data["meta"] = json.dumps(data["meta"])

        all_cols = list(data.keys()) + list(origin_row.keys())
        quoted_cols = ", ".join(self._quote_ident(c) for c in all_cols)
        placeholders = ", ".join(
            self._placeholder(i) for i in range(1, len(all_cols) + 1)
        )
        values = list(data.values()) + list(origin_row.values())

        return await self._insert(
            db,
            f"INSERT INTO dialog_items ({quoted_cols}) VALUES ({placeholders}){self._insert_returning_suffix()}",
            tuple(values),
        )

    async def get_branch(self, last_item_id: int) -> list[DialogItem]:
        db = await self._get_db()
        for origin_cls in ORIGIN_REGISTRY.values():
            await self._migrate_columns(origin_cls)

        rows = await self._fetchall(
            db,
            f"""
            WITH RECURSIVE branch AS (
                SELECT * FROM dialog_items WHERE item_id = {self._placeholder(1)}
                UNION ALL
                SELECT d.* FROM dialog_items d JOIN branch b ON d.item_id = b.previous_item_id
            )
            SELECT * FROM branch ORDER BY item_id
        """,
            (last_item_id,),
        )

        result: list[DialogItem] = []
        for row in rows:
            origin_cls = self._find_origin_class(row)
            origin = self._row_to_origin(row, origin_cls)

            result.append(
                DialogItem(
                    item_id=row["item_id"],
                    content=row["content"],
                    item_type=DialogItemType(row["item_type"]),
                    user=row["user"],
                    role=DialogRole(row["role"]),
                    origin=origin,
                    previous_item_id=row["previous_item_id"],
                    external_id=row["external_id"],
                    created_at=row["created_at"],
                    meta=json.loads(row["meta"]) if row["meta"] else {},
                )
            )
        return result

    async def find_item_id_by_external_id(
        self, external_id: str, origin: DialogOrigin
    ) -> int | None:
        db = await self._get_db()
        await self._migrate_columns(type(origin))
        origin_row = self._origin_to_row(origin)
        conditions = [f"external_id = {self._placeholder(1)}"]
        for i, col in enumerate(origin_row):
            conditions.append(f"{self._quote_ident(col)} = {self._placeholder(i + 2)}")
        values = [external_id] + list(origin_row.values())
        rows = await self._fetchall(
            db,
            f"SELECT item_id FROM dialog_items WHERE {' AND '.join(conditions)}",
            tuple(values),
        )
        return rows[0]["item_id"] if rows else None

    async def execute(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        db = await self._get_db()
        result = await self._fetchall(db, query, params)
        await self._commit(db)
        return result

    async def close(self) -> None:
        await self._close()

    async def stop(self) -> None:
        await self._close()
