# builtin/sql/sqlite_storage.py

from __future__ import annotations

from typing import Any, TYPE_CHECKING
from pathlib import Path
import aiosqlite

from .sql_storage import SqlStorage
from ...components.config import ConfigField
from ...utils import commamatrix_dir

if TYPE_CHECKING:
    from ...core.agent import Agent

sqlite_path = ConfigField[str](name="sqlite_path", default="db.sqlite", description="Database file under commamatrix_dir")


class SqliteStorage(SqlStorage):
    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        self._path = str(Path(self.config.get(commamatrix_dir)) / self.config.get(sqlite_path))

    async def _connect(self) -> aiosqlite.Connection:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(self._path)
        db.row_factory = aiosqlite.Row
        return db

    async def _execute(self, db: aiosqlite.Connection, query: str, params: tuple = ()) -> Any:
        return await db.execute(query, params)

    async def _fetchall(self, db: aiosqlite.Connection, query: str, params: tuple = ()) -> list:
        return list(await db.execute_fetchall(query, params))

    async def _schema(self) -> list[str]:
        tables = await self.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
        result: list[str] = []
        for table_row in tables:
            table_name = str(table_row["name"])
            quoted_name = f'"{table_name.replace(chr(34), chr(34) * 2)}"'
            columns = await self.execute(f"PRAGMA table_info({quoted_name})")
            column_text = ", ".join(
                f"{column['name']} ({column['type'] or 'unknown'})"
                for column in columns
            )
            result.append(f"{table_name}: {column_text}")
        return result

    async def _table_columns(self, db: aiosqlite.Connection, table_name: str) -> set[str]:
        rows = await db.execute_fetchall(f'PRAGMA table_info("{table_name}")')
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
