# builtin/fs/file_storage.py

import uuid
import aiofiles
from pathlib import Path

from ...api.config import ConfigField
from ...api.file_storage import FileStorage

file_store_dir = ConfigField[str](default='./files', description='Directory for SimpleFileStorage.')
file_store_prefix = ConfigField[str](default='file_', description='File name prefix (e.g. file_ → file_<uuid>).')


class SimpleFileStorage(FileStorage):

    @classmethod
    async def save(cls, data: bytes, ext: str | None = None) -> str:
        base = Path(file_store_dir.get())
        base.mkdir(parents=True, exist_ok=True)
        prefix = file_store_prefix.get()
        file_id = f'{prefix}{uuid.uuid4().hex}{ext or ""}'
        path = base / file_id
        async with aiofiles.open(path, 'wb') as f:
            await f.write(data)
        return file_id

    @classmethod
    async def get(cls, file_id: str) -> bytes | None:
        base = Path(file_store_dir.get())
        path = base / file_id
        try:
            async with aiofiles.open(path, 'rb') as f:
                return await f.read()
        except FileNotFoundError:
            return None

    @classmethod
    async def delete(cls, file_id: str) -> bool:
        base = Path(file_store_dir.get())
        path = base / file_id
        try:
            await aiofiles.os.remove(path)
        except FileNotFoundError:
            return False
        return True
