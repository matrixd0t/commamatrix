# tests/test_storage.py

"""Tests for Storage, SqliteStorage, SimpleFileStorage."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from commamatrix.components.config import Config
from commamatrix.components.dialog import DialogItem, DialogItemType, DialogRole
from commamatrix.components.storage import STORAGE_ATTRIBUTE, Storage
from commamatrix.components.file_storage import FILE_STORAGE_ATTRIBUTE, FileStorage
from tests.conftest import stub_agent, stub_origin


class TestStorageAttribute:
    def test_concrete_subclass_stamps(self):
        class MyStorage(Storage):
            async def save_event(self, entry): return None
            async def get_branch(self, last_item_id): return []
            async def find_item_id_by_external_id(self, external_id, origin): return None
        assert getattr(MyStorage, STORAGE_ATTRIBUTE, False) is True

    def test_abstract_not_stamped(self):
        assert getattr(Storage, STORAGE_ATTRIBUTE, False) is False


class TestFileStorageAttribute:
    def test_concrete_subclass_stamps(self):
        class MyFS(FileStorage):
            async def save(self, data, ext=None): return ""
            async def get(self, file_id): return None
            async def delete(self, file_id): return False
        assert getattr(MyFS, FILE_STORAGE_ATTRIBUTE, False) is True

    def test_abstract_not_stamped(self):
        assert getattr(FileStorage, FILE_STORAGE_ATTRIBUTE, False) is False


class TestSqliteStorage:
    @pytest.mark.asyncio
    async def test_save_and_get_branch(self):
        from commamatrix.builtin.sql.sqlite_storage import SqliteStorage, sqlite_path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            agent = stub_agent()
            agent.config = Config(overrides={sqlite_path: db_path})
            storage = SqliteStorage(agent=agent)
            await storage.start()

            origin = stub_origin()
            item = DialogItem(
                content="hello",
                item_type=DialogItemType.INPUT,
                role=DialogRole.USER,
                origin=origin,
                user="u1",
            )
            item_id = await storage.save_event(item)
            assert item_id is not None

            branch = await storage.get_branch(item_id)
            assert len(branch) == 1
            assert branch[0].content == "hello"
            assert branch[0].item_id == item_id

            await storage.stop()

    @pytest.mark.asyncio
    async def test_find_by_external_id(self):
        from commamatrix.builtin.sql.sqlite_storage import SqliteStorage, sqlite_path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            agent = stub_agent()
            agent.config = Config(overrides={sqlite_path: db_path})
            storage = SqliteStorage(agent=agent)
            await storage.start()

            origin = stub_origin()
            item = DialogItem(
                content="msg",
                item_type=DialogItemType.INPUT,
                role=DialogRole.USER,
                origin=origin,
                external_id="ext_123",
            )
            item_id = await storage.save_event(item)
            found_id = await storage.find_item_id_by_external_id("ext_123", origin)
            assert found_id == item_id

            not_found = await storage.find_item_id_by_external_id("missing", origin)
            assert not_found is None

            await storage.stop()

    @pytest.mark.asyncio
    async def test_get_branch_empty(self):
        from commamatrix.builtin.sql.sqlite_storage import SqliteStorage, sqlite_path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            agent = stub_agent()
            agent.config = Config(overrides={sqlite_path: db_path})
            storage = SqliteStorage(agent=agent)
            await storage.start()

            branch = await storage.get_branch(999)
            assert branch == []

            await storage.stop()


class TestSimpleFileStorage:
    @pytest.mark.asyncio
    async def test_save_and_get(self):
        from commamatrix.builtin.simple_fs import SimpleFileStorage, files_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = stub_agent()
            agent.config = Config(overrides={files_dir: tmpdir})
            fs = SimpleFileStorage(agent=agent)
            await fs.start()

            file_id = await fs.save(b"hello world", ext=".txt")
            assert len(file_id) == 36
            assert file_id.endswith(".txt")

            data = await fs.get(file_id)
            assert data == b"hello world"

            await fs.stop()

    @pytest.mark.asyncio
    async def test_get_nonexistent(self):
        from commamatrix.builtin.simple_fs import SimpleFileStorage, files_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = stub_agent()
            agent.config = Config(overrides={files_dir: tmpdir})
            fs = SimpleFileStorage(agent=agent)
            await fs.start()

            data = await fs.get("nonexistent_file")
            assert data is None

            await fs.stop()

    @pytest.mark.asyncio
    async def test_delete_existing(self):
        from commamatrix.builtin.simple_fs import SimpleFileStorage, files_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = stub_agent()
            agent.config = Config(overrides={files_dir: tmpdir})
            fs = SimpleFileStorage(agent=agent)
            await fs.start()

            file_id = await fs.save(b"data")
            assert await fs.delete(file_id) is True
            assert await fs.get(file_id) is None

            await fs.stop()

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        from commamatrix.builtin.simple_fs import SimpleFileStorage, files_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = stub_agent()
            agent.config = Config(overrides={files_dir: tmpdir})
            fs = SimpleFileStorage(agent=agent)
            await fs.start()

            assert await fs.delete("nonexistent") is False

            await fs.stop()
