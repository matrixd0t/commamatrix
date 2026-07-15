# builtin/fs/file_storage.py

from __future__ import annotations

import uuid
from aiofiles import open, os
from pathlib import Path

from ...api.file_storage import FileStorage
from ...api.config import ConfigField, Config

files_directory = ConfigField[str](name='files_directory', default='files', description='Directory for file storage')


class SimpleFileStorage(FileStorage):

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self._directory = Path(config.get(files_directory))
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
