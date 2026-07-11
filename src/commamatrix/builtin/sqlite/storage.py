# builtin/sqlite/storage.py

from __future__ import annotations

from typing import Any
import aiosqlite

from ..sql.storage import SqlStorage
from ...api.config import ConfigField

sqlite_path = ConfigField[str](default='db.sqlite', description='Path to SQLite database file')


class SqliteStorage(SqlStorage):

    def __init__(self, path: str | ConfigField[str] = sqlite_path) -> None:
        super().__init__()
        self._path = path.get() if isinstance(path, ConfigField) else path

    async def _connect(self) -> aiosqlite.Connection:
        db = await aiosqlite.connect(self._path)
        db.row_factory = aiosqlite.Row
        return db

    async def _execute(self, db: aiosqlite.Connection, query: str, params: tuple = ()) -> Any:
        return await db.execute(query, params)

    async def _fetchall(self, db: aiosqlite.Connection, query: str, params: tuple = ()) -> list:
        return list(await db.execute_fetchall(query, params))

    async def _insert(self, db: aiosqlite.Connection, query: str, params: tuple = ()) -> int | None:
        cursor = await db.execute(query, params)
        await self._commit(db)
        return cursor.lastrowid

    async def _commit(self, db: aiosqlite.Connection) -> None:
        await db.commit()

    async def _close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
