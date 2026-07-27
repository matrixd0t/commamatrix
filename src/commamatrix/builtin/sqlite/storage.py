# builtin/sqlite/storage.py

from __future__ import annotations

from typing import Any, TYPE_CHECKING
import aiosqlite

from ..sql.storage import SqlStorage
from ...components.config import ConfigField

if TYPE_CHECKING:
    from ...core.agent import Agent

sqlite_path = ConfigField[str](
    name="sqlite_path", default="db.sqlite", description="Path to SQLite database file"
)


class SqliteStorage(SqlStorage):
    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        self._path = self.config.get(sqlite_path)

    async def _connect(self) -> aiosqlite.Connection:
        db = await aiosqlite.connect(self._path)
        db.row_factory = aiosqlite.Row
        return db

    async def _execute(self, db: aiosqlite.Connection, query: str, params: tuple = ()) -> Any:
        return await db.execute(query, params)

    async def _fetchall(self, db: aiosqlite.Connection, query: str, params: tuple = ()) -> list:
        return list(await db.execute_fetchall(query, params))

    async def _columns(self, db: aiosqlite.Connection) -> set[str]:
        rows = await db.execute_fetchall("PRAGMA table_info(commamatrix_dialog)")
        return {row[1] for row in rows}

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
