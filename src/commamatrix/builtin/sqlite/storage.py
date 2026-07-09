from __future__ import annotations

from typing import Any
import aiosqlite

from ...api.config import ConfigField
from ..sql.storage import SqlStorage

sqlite_db_path = ConfigField[str](default=':memory:', description='Path to SQLite database file. Use ":memory:" for in-memory database.')


class SqliteStorage(SqlStorage):

    @classmethod
    async def _connect(cls) -> aiosqlite.Connection:
        db = await aiosqlite.connect(sqlite_db_path.get())
        db.row_factory = aiosqlite.Row
        return db

    @classmethod
    async def _execute(cls, db: aiosqlite.Connection, query: str, params: tuple = ()) -> Any:
        return await db.execute(query, params)

    @classmethod
    async def _fetchall(cls, db: aiosqlite.Connection, query: str, params: tuple = ()) -> list:
        return list(await db.execute_fetchall(query, params))

    @classmethod
    async def _insert(cls, db: aiosqlite.Connection, query: str, params: tuple = ()) -> int | None:
        cursor = await db.execute(query, params)
        await cls._commit(db)
        return cursor.lastrowid

    @classmethod
    async def _commit(cls, db: aiosqlite.Connection) -> None:
        await db.commit()

    @classmethod
    async def _close(cls) -> None:
        if cls._db is not None:
            await cls._db.close()
            cls._db = None
