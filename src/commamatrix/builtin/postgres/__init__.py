# builtin/postgres/__init__.py

from .storage import PostgresStorage, postgres_dsn

__all__ = ['PostgresStorage', 'postgres_dsn']
