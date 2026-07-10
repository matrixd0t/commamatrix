# builtin/fs/__init__.py

from .file_storage import SimpleFileStorage, file_store_dir, file_store_prefix

__all__ = ['SimpleFileStorage', 'file_store_dir', 'file_store_prefix']
