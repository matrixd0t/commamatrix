# builtin/simple_fs.py

from __future__ import annotations

import uuid
from aiofiles import open, os
from pathlib import Path

from typing import TYPE_CHECKING
from ..components.file_storage import FileStorage
from ..components.config import ConfigField

if TYPE_CHECKING:
    from ..core.agent import Agent

files_directory = ConfigField[str](name='files_directory', default='commamatrix_files', description='Directory for file storage')


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

    async def _resolve_path(self, file_id: str) -> Path | None:
        candidates = [file_id]
        if not file_id.startswith(self._prefix):
            candidates.append(f'{self._prefix}{file_id}')

        for c in candidates:
            path = self._directory / c
            try:
                async with open(path, 'rb'):
                    return path
            except FileNotFoundError:
                pass

            if '.' not in c:
                try:
                    for entry in self._directory.iterdir():
                        if entry.name.startswith(c + '.') and entry.is_file():
                            return entry
                except FileNotFoundError:
                    return None

        return None

    async def get(self, file_id: str) -> bytes | None:
        path = await self._resolve_path(file_id)
        if path is None:
            return None
        return await open(path, 'rb').read()

    async def delete(self, file_id: str) -> bool:
        path = await self._resolve_path(file_id)
        if path is None:
            return False
        try:
            await os.remove(path)
        except FileNotFoundError:
            return False
        return True


__all__ = [
    "files_directory",
    "SimpleFileStorage"
]
