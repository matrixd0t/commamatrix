# builtin/fs/file_storage.py

import uuid
import aiofiles
from pathlib import Path

from ...api.file_storage import FileStorage


class SimpleFileStorage(FileStorage):

    def __init__(self, directory: str = './files', prefix: str = 'file_') -> None:
        self._directory = Path(directory)
        self._prefix = prefix

    async def save(self, data: bytes, ext: str | None = None) -> str:
        self._directory.mkdir(parents=True, exist_ok=True)
        file_id = f'{self._prefix}{uuid.uuid4().hex}{ext or ""}'
        path = self._directory / file_id
        async with aiofiles.open(path, 'wb') as f:
            await f.write(data)
        return file_id

    async def get(self, file_id: str) -> bytes | None:
        path = self._directory / file_id
        try:
            async with aiofiles.open(path, 'rb') as f:
                return await f.read()
        except FileNotFoundError:
            return None

    async def delete(self, file_id: str) -> bool:
        path = self._directory / file_id
        try:
            await aiofiles.os.remove(path)
        except FileNotFoundError:
            return False
        return True
