# builtin/fs/file_storage.py

from __future__ import annotations

import uuid
from aiofiles import open, os
from pathlib import Path

from typing import TYPE_CHECKING
from ...components.file_storage import FileStorage
from ...components.config import ConfigField

if TYPE_CHECKING:
    from ...core.agent import Agent

files_directory = ConfigField[str](name='files_directory', default='files', description='Directory for file storage')


class SimpleFileStorage(FileStorage):

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        self._directory = Path(self.config.get(files_directory))
        self._prefix = 'file_'

    async def save(self, data: bytes, ext: str | None = None) -> str:
        self._directory.mkdir(parents=True, exist_ok=True)
        file_id = f'{self._prefix}{uuid.uuid4().hex}{ext or ""}'
        path = self._directory / file_id
        async with open(path, 'wb') as f:
            await f.write(data)
        return file_id

    async def get(self, file_id: str) -> bytes | None:
        path = self._directory / file_id
        try:
            async with open(path, 'rb') as f:
                return await f.read()
        except FileNotFoundError:
            return None

    async def delete(self, file_id: str) -> bool:
        path = self._directory / file_id
        try:
            await os.remove(path)
        except FileNotFoundError:
            return False
        return True
