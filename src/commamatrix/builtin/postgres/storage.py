# builtin/postgres/storage.py

from __future__ import annotations

from typing import Any
import asyncpg

from ...api.config import ConfigField
from ..sql.storage import SqlStorage

pg_dsn = ConfigField[str](init=True, description='PostgreSQL connection URL (e.g. postgresql://user:pass@host:port/dbname)')


class PostgresStorage(SqlStorage):

    @classmethod
    async def _connect(cls) -> asyncpg.Connection:
        return await asyncpg.connect(dsn=pg_dsn.get())

    @classmethod
    async def _execute(cls, db: asyncpg.Connection, query: str, params: tuple = ()) -> Any:
        return await db.execute(query, *params)

    @classmethod
    async def _fetchall(cls, db: asyncpg.Connection, query: str, params: tuple = ()) -> list:
        return await db.fetch(query, *params)

    @classmethod
    async def _insert(cls, db: asyncpg.Connection, query: str, params: tuple = ()) -> int | None:
        row = await db.fetchrow(query, *params)
        return row['item_id']

    @classmethod
    async def _commit(cls, db: asyncpg.Connection) -> None:
        pass

    @classmethod
    async def _close(cls) -> None:
        if cls._db is not None:
            await cls._db.close()
            cls._db = None

    @classmethod
    def _placeholder(cls, index: int) -> str:
        return f'${index}'

    @classmethod
    def _quote_ident(cls, name: str) -> str:
        return f'"{name}"'

    @classmethod
    def _pk_type(cls) -> str:
        return 'SERIAL PRIMARY KEY'

    @classmethod
    def _insert_returning_suffix(cls) -> str:
        return ' RETURNING item_id'
