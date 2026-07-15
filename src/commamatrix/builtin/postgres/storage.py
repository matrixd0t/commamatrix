# builtin/postgres/storage.py

from __future__ import annotations

from typing import Any, TYPE_CHECKING
import asyncpg

from ..sql.storage import SqlStorage
from ...components.config import ConfigField

if TYPE_CHECKING:
    from ...core.agent import Agent

postgres_dsn = ConfigField[str](
    name="postgres_dsn", description='PostgreSQL connection DSN: "user:password@host:port/database"'
)


class PostgresStorage(SqlStorage):
    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        self._dsn = self.config.get(postgres_dsn)
        if self._dsn is None:
            raise ValueError("postgres_dsn is required for PostgresStorage")

    async def _connect(self) -> asyncpg.Connection:
        return await asyncpg.connect(dsn=self._dsn)

    async def _execute(
        self, db: asyncpg.Connection, query: str, params: tuple = ()
    ) -> Any:
        return await db.execute(query, *params)

    async def _fetchall(
        self, db: asyncpg.Connection, query: str, params: tuple = ()
    ) -> list:
        return await db.fetch(query, *params)

    async def _columns(self, db: asyncpg.Connection) -> set[str]:
        rows = await db.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
            "dialog_items",
        )
        return {row["column_name"] for row in rows}

    async def _insert(
        self, db: asyncpg.Connection, query: str, params: tuple = ()
    ) -> int | None:
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
