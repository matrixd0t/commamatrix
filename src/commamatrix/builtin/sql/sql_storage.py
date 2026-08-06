# builtin/sql/sql_storage.py

from __future__ import annotations

import json
from abc import abstractmethod
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
from ...components.table import TableDescriptor

if TYPE_CHECKING:
    from ...core.agent import Agent
    from pydantic import BaseModel

BaseColumns = set(DialogItem.model_fields.keys()) - {"origin"} | set(DialogOrigin.model_fields.keys())


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


def _sql_literal(value: Any) -> str | None:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def _field_is_nullable(field_info) -> bool:
    ann = field_info.annotation
    if ann is type(None):
        return True
    origin = get_origin(ann)
    if origin is Union or origin is UnionType:
        args = get_args(ann)
        return any(a is type(None) for a in args)
    return False


def _format_schema_column(name: str, _type: str, *, null: bool, primary_key: bool = False, default: Any = None, inc: bool = False) -> str:
    parts = [f"{name} {_type or 'unknown'}"]
    if primary_key:
        parts.append("PRIMARY KEY")
    if inc:
        parts.append("AUTOINCREMENT")
    elif not null and not primary_key:
        parts.append("NOT NULL")
    if default is not None:
        parts.append(f"DEFAULT {default}")
    return " ".join(parts)


class SqlStorage(Storage):
    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
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
    async def _table_columns(self, db: Any, table_name: str) -> set[str]:
        """Return the current column names for a table."""
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
            self.logger.info("Storage connecting backend=%s", type(self).__name__)
            self._db = await self._connect()
            await self._init_db()
            self.logger.info("Storage connected backend=%s", type(self).__name__)
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
            CREATE TABLE IF NOT EXISTS commamatrix_dialog (
                {columns_sql}
            )
        """,
        )
        await self._commit(db)
        await self._ensure_schema_versions(db)

        self._known_columns = await self._table_columns(db, "commamatrix_dialog")

        await self._migrate_columns(DialogItem, skip={"origin"})
        await self._migrate_columns(DialogOrigin)
        for origin_cls in ORIGIN_REGISTRY.values():
            await self._migrate_columns(origin_cls)

    async def _migrate_columns(self, model_cls: type[BaseModel], skip: set[str] | None = None) -> None:
        skip = skip or set()
        db = self._db
        for name, field_info in model_cls.model_fields.items():
            if name in skip or name in self._known_columns:
                continue
            sql_type = python_type_to_sql(field_info.annotation)
            try:
                await self._execute(db, f"ALTER TABLE commamatrix_dialog ADD COLUMN {self._quote_ident(name)} {sql_type}")
                await self._commit(db)
            except Exception as exc:
                self._known_columns = await self._table_columns(db, "commamatrix_dialog")
                if name not in self._known_columns:
                    raise RuntimeError(f"Failed to migrate commamatrix_dialog.{name}") from exc
            self._known_columns.add(name)
            self.logger.debug("Storage schema column added table=commamatrix_dialog column=%s", name)

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

        item_id = await self._insert(
            db,
            f"INSERT INTO commamatrix_dialog ({quoted_cols}) VALUES ({placeholders}){self._insert_returning_suffix()}",
            tuple(values),
        )
        self.logger.debug("Storage event saved item_type=%s id_present=%s", entry.item_type.value, item_id is not None)
        return item_id

    async def get_branch(self, last_item_id: int) -> list[DialogItem]:
        db = await self._get_db()
        for origin_cls in ORIGIN_REGISTRY.values():
            await self._migrate_columns(origin_cls)

        rows = await self._fetchall(
            db,
            f"""
            WITH RECURSIVE branch AS (
                SELECT commamatrix_dialog.*, 0 AS depth
                FROM commamatrix_dialog
                WHERE item_id = {self._placeholder(1)}
                UNION ALL
                SELECT d.*, b.depth + 1
                FROM commamatrix_dialog d
                JOIN branch b ON d.item_id = b.previous_item_id
            )
            SELECT * FROM branch ORDER BY depth DESC
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
        self.logger.debug("Storage branch loaded items=%d", len(result))
        return result

    async def find_item_id_by_external_id(self, external_id: str, origin: DialogOrigin) -> int | None:
        db = await self._get_db()
        await self._migrate_columns(type(origin))
        origin_row = self._origin_to_row(origin)
        conditions = [f"external_id = {self._placeholder(1)}"]
        for i, col in enumerate(origin_row):
            conditions.append(f"{self._quote_ident(col)} = {self._placeholder(i + 2)}")
        values = [external_id] + list(origin_row.values())
        rows = await self._fetchall(
            db,
            f"SELECT item_id FROM commamatrix_dialog WHERE {' AND '.join(conditions)}",
            tuple(values),
        )
        item_id = rows[0]["item_id"] if rows else None
        self.logger.debug("Storage external item lookup found=%s", item_id is not None)
        return item_id

    async def get_history(self, *, origin_type: type[DialogOrigin] | None = None, origin_fields: dict[str, Any] | None = None) -> list[DialogItem]:
        """Return persisted items filtered by origin fields."""
        db = await self._get_db()
        await self._migrate_columns(DialogOrigin)
        if origin_type is not None:
            await self._migrate_columns(origin_type)
        conditions: list[str] = []
        params: list[Any] = []
        if origin_type is not None:
            conditions.append(f"origin_type = {self._placeholder(len(params) + 1)}")
            params.append(origin_type.model_fields["origin_type"].default)
            for name, value in (origin_fields or {}).items():
                if name not in origin_type.model_fields:
                    raise ValueError(f"Unknown origin field: {name}")
                conditions.append(f"{self._quote_ident(name)} = {self._placeholder(len(params) + 1)}")
                params.append(value)
        elif origin_fields:
            raise ValueError("origin_values requires origin_type")

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = await self._fetchall(
            db,
            f"SELECT * FROM commamatrix_dialog{where} ORDER BY item_id ASC",
            tuple(params),
        )
        result: list[DialogItem] = []
        for row in rows:
            origin_cls = self._find_origin_class(row)
            origin = self._row_to_origin(row, origin_cls)
            result.append(DialogItem(
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
            ))
        self.logger.debug("Storage history loaded items=%d", len(result))
        return result

    @property
    def schema_backend(self) -> SqlStorage:
        return self

    async def _ensure_schema_versions(self, db: Any) -> None:
        await self._execute(
            db,
            """
            CREATE TABLE IF NOT EXISTS commamatrix_schema_versions (
                table_id TEXT PRIMARY KEY,
                table_name TEXT NOT NULL,
                version INTEGER NOT NULL
            )
            """,
        )
        await self._commit(db)

    async def _schema_version(self, db: Any, table_id: str) -> int | None:
        rows = await self._fetchall(
            db,
            f"SELECT version FROM commamatrix_schema_versions WHERE table_id = {self._placeholder(1)}",
            (table_id,),
        )
        return int(rows[0]["version"]) if rows else None

    async def _record_schema_version(
        self,
        db: Any,
        table: TableDescriptor,
    ) -> None:
        placeholders = ", ".join(self._placeholder(index) for index in range(1, 4))
        await self._execute(
            db,
            f"""
            INSERT INTO commamatrix_schema_versions (table_id, table_name, version)
            VALUES ({placeholders})
            ON CONFLICT (table_id) DO UPDATE SET
                table_name = EXCLUDED.table_name,
                version = EXCLUDED.version
            """,
            (
                table.table_cls.resolved_table_id(),
                table.table_cls.table_name,
                table.table_cls.version,
            ),
        )
        await self._commit(db)

    def _table_columns_sql(self, table: TableDescriptor) -> list[str]:
        table_cls = table.table_cls
        fields = table_cls.row_model.model_fields
        if not fields:
            raise ValueError(
                f"Plugin table {table_cls.resolved_table_id()!r} must define at least one field"
            )

        columns: list[str] = []
        for name, field_info in fields.items():
            if name == table_cls.auto_increment:
                column = f"{self._quote_ident(name)} {self._pk_type()}"
            else:
                column = f"{self._quote_ident(name)} {python_type_to_sql(field_info.annotation)}"
            if name == table_cls.primary_key and name != table_cls.auto_increment:
                column += " PRIMARY KEY"
            elif not _field_is_nullable(field_info):
                if name != table_cls.auto_increment:
                    column += " NOT NULL"
            if not field_info.is_required() and field_info.default_factory is None:
                if (default := _sql_literal(field_info.default)) is not None:
                    column += f" DEFAULT {default}"
            columns.append(column)
        return columns

    async def _ensure_indexes(self, db: Any, table: TableDescriptor) -> None:
        table_cls = table.table_cls
        table_name = self._quote_ident(table_cls.table_name)
        for index_number, index_fields in enumerate(table_cls.indexes):
            index_name = self._quote_ident(f"idx_{table_cls.table_name}_{index_number}")
            index_columns = ", ".join(self._quote_ident(name) for name in index_fields)
            await self._execute(
                db,
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({index_columns})",
            )
        for index_number, index_fields in enumerate(table_cls.unique_indexes):
            index_name = self._quote_ident(f"uidx_{table_cls.table_name}_{index_number}")
            index_columns = ", ".join(self._quote_ident(name) for name in index_fields)
            await self._execute(
                db,
                f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table_name} ({index_columns})",
            )
        await self._commit(db)

    async def ensure_table(self, table: TableDescriptor) -> None:
        db = await self._get_db()
        table_cls = table.table_cls
        existing_columns = await self._table_columns(db, table_cls.table_name)
        if not existing_columns:
            table_name = self._quote_ident(table_cls.table_name)
            columns = ", ".join(self._table_columns_sql(table))
            await self._execute(
                db,
                f"CREATE TABLE IF NOT EXISTS {table_name} ({columns})",
            )
            await self._commit(db)
            await self._record_schema_version(db, table)
        else:
            table_id = table_cls.resolved_table_id()
            current_version = await self._schema_version(db, table_id)
            current_version = 1 if current_version is None else current_version
            if current_version > table_cls.version:
                raise RuntimeError(
                    f"Cannot downgrade table {table_id!r} from "
                    f"version {current_version} to {table_cls.version}"
                )
            if current_version < table_cls.version:
                await table_cls.migrate(self, current_version)
                await self._record_schema_version(db, table)

        await self._ensure_indexes(db, table)
        self.logger.debug("Storage table ensured table=%s version=%d", table_cls.table_name, table_cls.version)

    async def add_column(self, table_name: str, column_name: str, sql_type: str, *, nullable: bool = True) -> None:
        db = await self._get_db()
        null_sql = "" if nullable else " NOT NULL"
        await self._execute(
            db,
            f"ALTER TABLE {self._quote_ident(table_name)} "
            f"ADD COLUMN {self._quote_ident(column_name)} {sql_type}{null_sql}",
        )
        await self._commit(db)

    async def schema(self) -> list[str]:
        """Return DDL-like table descriptions including column constraints."""
        return await self._schema()

    async def _schema(self) -> list[str]:
        raise NotImplementedError

    async def execute(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        db = await self._get_db()
        result = await self._fetchall(db, query, params)
        await self._commit(db)
        self.logger.debug("Storage query completed rows=%d", len(result))
        return result

    async def start(self) -> None:
        await self._get_db()
        self.logger.info("Storage started backend=%s", type(self).__name__)

    async def close(self) -> None:
        await self._close()

    async def stop(self) -> None:
        await self._close()
        self.logger.info("Storage stopped backend=%s", type(self).__name__)
