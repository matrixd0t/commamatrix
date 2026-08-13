# tests/test_tables.py

from __future__ import annotations

import pytest

from commamatrix import Agent
from commamatrix.builtin.http_connector import UserNamesTable as HttpUserNamesTable
from commamatrix.builtin.multi_user import UserNamesTable
from commamatrix.builtin.sql.sqlite_storage import sqlite_path
from commamatrix.utils import commamatrix_dir


def test_http_connector_reuses_multi_user_names_table():
    assert HttpUserNamesTable is UserNamesTable
    assert UserNamesTable.__module__ == "commamatrix.builtin.multi_user"
    assert UserNamesTable.table_name == "commamatrix_user_names"


@pytest.mark.asyncio
async def test_multi_user_table_is_created_when_extension_is_active(tmp_path):
    agent = Agent(
        "table-test",
        config={commamatrix_dir: str(tmp_path), sqlite_path: "test.db"},
        auto_load_main=False,
        auto_load_plugins=False,
    )
    await agent.add_extensions("commamatrix.builtin.multi_user")
    await agent.start()
    try:
        rows = await agent.storage.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (UserNamesTable.table_name,),
        )
        assert len(rows) == 1
        assert rows[0]["name"] == "commamatrix_user_names"
    finally:
        await agent.stop()
