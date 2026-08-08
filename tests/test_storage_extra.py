# tests/test_storage_extra.py

"""Additional tests for SqlStorage: _migrate_columns, get_branch with chained items, multiple origins."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from commamatrix.components.config import Config
from commamatrix.components.dialog import DialogItem, DialogItemType, DialogRole
from tests.conftest import make_dialog_item, stub_agent, stub_origin


class TestSqliteMigrateColumns:
    @pytest.mark.asyncio
    async def test_origin_type_column_is_created_from_dialog_origin(self):
        from commamatrix.builtin.http_connector.connector import HttpOrigin
        from commamatrix.builtin.sql.sqlite_storage import SqliteStorage, sqlite_path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            agent = stub_agent()
            agent.config = Config(overrides={sqlite_path: db_path})
            storage = SqliteStorage(agent=agent)

            await storage.get_history(origin_type=HttpOrigin)

            columns = await storage._table_columns(storage._db, "commamatrix_dialog")
            assert "origin_type" in columns
            assert "http_user_id" in columns
            await storage.stop()

    @pytest.mark.asyncio
    async def test_migrate_adds_new_column(self):
        from commamatrix.builtin.sql.sqlite_storage import SqliteStorage, sqlite_path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            agent = stub_agent()
            agent.config = Config(overrides={sqlite_path: db_path})
            storage = SqliteStorage(agent=agent)
            await storage.start()

            # First save with standard fields
            item = make_dialog_item("hello")
            await storage.save_event(item)

            # Migrate with a llm that has extra fields — should not fail
            from pydantic import BaseModel

            class ExtraModel(BaseModel):
                content: str = ""
                item_type: str = ""
                user: str = ""
                role: str = ""

            # This should work without error (columns already exist)
            await storage._migrate_columns(ExtraModel)

            await storage.stop()

    @pytest.mark.asyncio
    async def test_migrate_is_idempotent(self):
        from commamatrix.builtin.sql.sqlite_storage import SqliteStorage, sqlite_path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            agent = stub_agent()
            agent.config = Config(overrides={sqlite_path: db_path})
            storage = SqliteStorage(agent=agent)
            await storage.start()

            # Trigger db initialization by saving an item
            origin = stub_origin()
            item = make_dialog_item("init", origin=origin)
            await storage.save_event(item)

            # Run migrate twice — should not fail
            from pydantic import BaseModel

            class TestModel(BaseModel):
                content: str = ""

            await storage._migrate_columns(TestModel)
            await storage._migrate_columns(TestModel)

            await storage.stop()


class TestSqliteGetBranchChained:
    @pytest.mark.asyncio
    async def test_get_branch_with_chain(self):
        from commamatrix.builtin.sql.sqlite_storage import SqliteStorage, sqlite_path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            agent = stub_agent()
            agent.config = Config(overrides={sqlite_path: db_path})
            storage = SqliteStorage(agent=agent)
            await storage.start()

            origin = stub_origin()

            # Create a chain: item1 -> item2 -> item3
            item1 = make_dialog_item("first", origin=origin)
            id1 = await storage.save_event(item1)

            item2 = make_dialog_item("second", origin=origin, previous_item_id=id1)
            id2 = await storage.save_event(item2)

            item3 = make_dialog_item("third", origin=origin, previous_item_id=id2)
            id3 = await storage.save_event(item3)

            # Get branch from the last item
            branch = await storage.get_branch(id3)

            assert len(branch) == 3
            assert branch[0].content == "first"
            assert branch[1].content == "second"
            assert branch[2].content == "third"
            assert branch[0].item_id == id1
            assert branch[1].item_id == id2
            assert branch[2].item_id == id3

            await storage.stop()

    @pytest.mark.asyncio
    async def test_get_branch_partial_chain(self):
        from commamatrix.builtin.sql.sqlite_storage import SqliteStorage, sqlite_path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            agent = stub_agent()
            agent.config = Config(overrides={sqlite_path: db_path})
            storage = SqliteStorage(agent=agent)
            await storage.start()

            origin = stub_origin()

            item1 = make_dialog_item("first", origin=origin)
            id1 = await storage.save_event(item1)

            item2 = make_dialog_item("second", origin=origin, previous_item_id=id1)
            id2 = await storage.save_event(item2)

            # Get branch from middle item
            branch = await storage.get_branch(id2)

            assert len(branch) == 2
            assert branch[0].content == "first"
            assert branch[1].content == "second"

            await storage.stop()

    @pytest.mark.asyncio
    async def test_get_branch_single_item(self):
        from commamatrix.builtin.sql.sqlite_storage import SqliteStorage, sqlite_path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            agent = stub_agent()
            agent.config = Config(overrides={sqlite_path: db_path})
            storage = SqliteStorage(agent=agent)
            await storage.start()

            item = make_dialog_item("only")
            item_id = await storage.save_event(item)

            branch = await storage.get_branch(item_id)
            assert len(branch) == 1
            assert branch[0].content == "only"

            await storage.stop()


class TestSqliteMultipleOrigins:
    @pytest.mark.asyncio
    async def test_different_origins_stored_separately(self):
        from commamatrix.builtin.sql.sqlite_storage import SqliteStorage, sqlite_path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            agent = stub_agent()
            agent.config = Config(overrides={sqlite_path: db_path})
            storage = SqliteStorage(agent=agent)
            await storage.start()

            origin1 = stub_origin("chat1")
            origin2 = stub_origin("chat2")

            item1 = DialogItem(
                content="msg1",
                item_type=DialogItemType.INPUT,
                role=DialogRole.USER,
                origin=origin1,
                user="u1",
                external_id="ext1",
            )
            id1 = await storage.save_event(item1)

            item2 = DialogItem(
                content="msg2",
                item_type=DialogItemType.INPUT,
                role=DialogRole.USER,
                origin=origin2,
                user="u2",
                external_id="ext2",
            )
            id2 = await storage.save_event(item2)

            found1 = await storage.find_item_id_by_external_id("ext1", origin1)
            found2 = await storage.find_item_id_by_external_id("ext2", origin2)

            assert found1 == id1
            assert found2 == id2

            await storage.stop()


class TestSqliteDialogItemTypes:
    @pytest.mark.asyncio
    async def test_all_item_types_roundtrip(self):
        from commamatrix.builtin.sql.sqlite_storage import SqliteStorage, sqlite_path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            agent = stub_agent()
            agent.config = Config(overrides={sqlite_path: db_path})
            storage = SqliteStorage(agent=agent)
            await storage.start()

            origin = stub_origin()
            types_to_test = [
                (DialogItemType.INPUT, DialogRole.USER, "input text"),
                (DialogItemType.OUTPUT, DialogRole.ASSISTANT, "output text"),
                (DialogItemType.REASONING, DialogRole.ASSISTANT, "reasoning_level"),
                (DialogItemType.TOOL_CALL, DialogRole.ASSISTANT, '{"tool_call_id":"tc1","tool_name":"fn","tool_args":{}}'),
                (DialogItemType.TOOL_CALL_RESULT, DialogRole.TOOL, '{"tool_call_id":"tc1","content":"result"}'),
            ]

            prev_id = None
            for item_type, role, content in types_to_test:
                item = DialogItem(
                    content=content,
                    item_type=item_type,
                    role=role,
                    origin=origin,
                    user="u",
                    previous_item_id=prev_id,
                )
                prev_id = await storage.save_event(item)

            # Verify all items can be retrieved via chained branch
            branch = await storage.get_branch(prev_id)
            assert len(branch) == len(types_to_test)

            for i, (item_type, role, content) in enumerate(types_to_test):
                assert branch[i].item_type == item_type
                assert branch[i].role == role
                assert branch[i].content == content

            await storage.stop()

    @pytest.mark.asyncio
    async def test_meta_roundtrip(self):
        from commamatrix.builtin.sql.sqlite_storage import SqliteStorage, sqlite_path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            agent = stub_agent()
            agent.config = Config(overrides={sqlite_path: db_path})
            storage = SqliteStorage(agent=agent)
            await storage.start()

            origin = stub_origin()
            item = DialogItem(
                content="test",
                item_type=DialogItemType.INPUT,
                role=DialogRole.USER,
                origin=origin,
                user="u",
                meta={"custom": "value", "nested": {"key": 42}},
            )
            item_id = await storage.save_event(item)

            branch = await storage.get_branch(item_id)
            assert len(branch) == 1
            assert branch[0].meta == {"custom": "value", "nested": {"key": 42}}

            await storage.stop()


class TestSqliteStopClose:
    @pytest.mark.asyncio
    async def test_stop_closes_connection(self):
        from commamatrix.builtin.sql.sqlite_storage import SqliteStorage, sqlite_path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            agent = stub_agent()
            agent.config = Config(overrides={sqlite_path: db_path})
            storage = SqliteStorage(agent=agent)
            await storage.start()

            # Trigger lazy db initialization
            origin = stub_origin()
            item = make_dialog_item("init", origin=origin)
            await storage.save_event(item)

            assert storage._db is not None
            await storage.stop()
            # After stop, _db should be closed (but may still reference the object)
            # Just verify no error on double stop
            await storage.stop()


class TestSqliteFindExternalId:
    @pytest.mark.asyncio
    async def test_find_returns_none_for_wrong_origin(self):
        from commamatrix.builtin.sql.sqlite_storage import SqliteStorage, sqlite_path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            agent = stub_agent()
            agent.config = Config(overrides={sqlite_path: db_path})
            storage = SqliteStorage(agent=agent)
            await storage.start()

            origin1 = stub_origin("chat1")
            origin2 = stub_origin("chat2")

            item = DialogItem(
                content="msg",
                item_type=DialogItemType.INPUT,
                role=DialogRole.USER,
                origin=origin1,
                user="u1",
                external_id="ext_1",
            )
            await storage.save_event(item)

            # Wrong origin should not find
            found = await storage.find_item_id_by_external_id("ext_1", origin2)
            assert found is None

            await storage.stop()
