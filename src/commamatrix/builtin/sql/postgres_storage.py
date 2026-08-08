# builtin/sql/postgres_storage.py

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import asyncpg

from ...components.config import ConfigField
from .sql_storage import SqlStorage, _format_schema_column

if TYPE_CHECKING:
    from ...core.agent import Agent

postgres_dsn = ConfigField[str](name="postgres_dsn", description='PostgreSQL connection DSN: "user:password@host:port/database"')


class PostgresStorage(SqlStorage):
    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        self._dsn = self.config.get(postgres_dsn)
        if self._dsn is None:
            raise ValueError("postgres_dsn is required for PostgresStorage")

    async def _connect(self) -> asyncpg.Connection:
        return await asyncpg.connect(dsn=self._dsn)

    async def _execute(self, db: asyncpg.Connection, query: str, params: tuple = ()) -> Any:
        return await db.execute(query, *params)

    async def _fetchall(self, db: asyncpg.Connection, query: str, params: tuple = ()) -> list:
        return await db.fetch(query, *params)

    async def _schema(self) -> list[str]:
        columns = await self.execute(
            """
            SELECT
                columns.table_schema,
                columns.table_name,
                columns.column_name,
                columns.data_type,
                columns.is_nullable,
                columns.column_default,
                EXISTS (
                    SELECT 1
                    FROM information_schema.table_constraints AS constraints
                    JOIN information_schema.key_column_usage AS key_columns
                      ON key_columns.constraint_catalog = constraints.constraint_catalog
                     AND key_columns.constraint_schema = constraints.constraint_schema
                     AND key_columns.constraint_name = constraints.constraint_name
                     AND key_columns.table_schema = constraints.table_schema
                     AND key_columns.table_name = constraints.table_name
                     AND key_columns.column_name = columns.column_name
                    WHERE constraints.constraint_type = 'PRIMARY KEY'
                      AND constraints.table_schema = columns.table_schema
                      AND constraints.table_name = columns.table_name
                ) AS is_primary_key
            FROM information_schema.columns AS columns
            WHERE columns.table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY columns.table_schema, columns.table_name, columns.ordinal_position
            """
        )
        tables: dict[str, list[str]] = {}
        for column in columns:
            schema = str(column["table_schema"])
            table_name = str(column["table_name"])
            display_name = table_name if schema == "public" else f"{schema}.{table_name}"
            tables.setdefault(display_name, []).append(
                _format_schema_column(str(column["column_name"]), str(column["data_type"]), null=column["is_nullable"] == "YES",
                                      primary_key=bool(column["is_primary_key"]), default=column["column_default"])
            )
        return [f"{name}: {', '.join(fields)}" for name, fields in tables.items()]

    async def _table_columns(self, db: asyncpg.Connection, table_name: str) -> set[str]:
        rows = await db.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
            table_name,
        )
        return {row["column_name"] for row in rows}

    async def _insert(self, db: asyncpg.Connection, query: str, params: tuple = ()) -> int | None:
        row = await db.fetchrow(query, *params)
        return row["item_id"]

    async def _commit(self, db: asyncpg.Connection) -> None:
        pass

    async def _close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _placeholder(self, index: int) -> str:
        return f"${index}"

    def _quote_ident(self, name: str) -> str:
        return f'"{name}"'

    def _pk_type(self) -> str:
        return "SERIAL PRIMARY KEY"

    def _insert_returning_suffix(self) -> str:
        return " RETURNING item_id"

    async def info(self) -> str:
        return f'PostgreSQL {self._dsn}'
