from __future__ import annotations

import json
from abc import ABC, abstractmethod
from types import UnionType
from typing import Any, Union, get_args, get_origin

from ...api.dialog import DialogItem, DialogOrigin, DialogItemType, DialogRole, ORIGIN_REGISTRY
from ...api.storage import Storage

BaseColumns = (set(DialogItem.model_fields.keys()) - {'origin'} | set(DialogOrigin.model_fields.keys()))


def python_type_to_sql(t: type) -> str:
    origin = get_origin(t)
    if origin is Union or origin is UnionType:
        args = [a for a in get_args(t) if a is not type(None)]
        t = args[0] if args else str
    if not isinstance(t, type):
        return 'TEXT'
    if issubclass(t, bool):
        return 'INTEGER'
    if issubclass(t, int):
        return 'INTEGER'
    if issubclass(t, float):
        return 'REAL'
    return 'TEXT'


def _field_is_nullable(field_info) -> bool:
    ann = field_info.annotation
    if ann is type(None):
        return True
    origin = get_origin(ann)
    if origin is Union or origin is UnionType:
        args = get_args(ann)
        return any(a is type(None) for a in args)
    return False


class SqlStorage(Storage, ABC):
    _known_columns: set[str] = set()
    _db: Any = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._known_columns = set(BaseColumns)
        cls._db = None

    @classmethod
    @abstractmethod
    async def _connect(cls) -> Any:
        ...

    @classmethod
    @abstractmethod
    async def _execute(cls, db: Any, query: str, params: tuple = ()) -> Any:
        ...

    @classmethod
    @abstractmethod
    async def _fetchall(cls, db: Any, query: str, params: tuple = ()) -> list:
        ...

    @classmethod
    @abstractmethod
    async def _insert(cls, db: Any, query: str, params: tuple = ()) -> int | None:
        ...

    @classmethod
    @abstractmethod
    async def _commit(cls, db: Any) -> None:
        ...

    @classmethod
    @abstractmethod
    async def _close(cls) -> None:
        ...

    @classmethod
    def _placeholder(cls, index: int) -> str:
        return '?'

    @classmethod
    def _quote_ident(cls, name: str) -> str:
        return name

    @classmethod
    def _pk_type(cls) -> str:
        return 'INTEGER PRIMARY KEY AUTOINCREMENT'

    @classmethod
    def _insert_returning_suffix(cls) -> str:
        return ''

    @classmethod
    def _col_sql(cls, name: str, field_info) -> str:
        if name == 'item_id':
            return f'{cls._quote_ident(name)} {cls._pk_type()}'
        sql_type = python_type_to_sql(field_info.annotation)
        nullable = _field_is_nullable(field_info)
        null_str = '' if nullable else ' NOT NULL'
        return f'{cls._quote_ident(name)} {sql_type}{null_str}'

    @classmethod
    async def _get_db(cls) -> Any:
        if cls._db is None:
            cls._db = await cls._connect()
            await cls._init_db()
        return cls._db

    @classmethod
    async def _init_db(cls) -> None:
        db = cls._db

        cols = []
        for name, field_info in DialogItem.model_fields.items():
            if name == 'origin':
                continue
            cols.append(cls._col_sql(name, field_info))
        for name, field_info in DialogOrigin.model_fields.items():
            cols.append(cls._col_sql(name, field_info))

        columns_sql = ',\n                '.join(cols)

        await cls._execute(db, f'''
            CREATE TABLE IF NOT EXISTS dialog_items (
                {columns_sql}
            )
        ''')
        await cls._commit(db)
        for origin_cls in ORIGIN_REGISTRY.values():
            await cls._add_origin_columns(origin_cls)

    @classmethod
    async def _add_origin_columns(cls, origin_cls: type[DialogOrigin]) -> None:
        db = cls._db
        for name, field_info in origin_cls.model_fields.items():
            if name in cls._known_columns:
                continue
            sql_type = python_type_to_sql(field_info.annotation)
            try:
                await cls._execute(db, f'ALTER TABLE dialog_items ADD COLUMN {cls._quote_ident(name)} {sql_type}')
                await cls._commit(db)
            except Exception:
                pass
            cls._known_columns.add(name)

    @staticmethod
    def _origin_to_row(origin: DialogOrigin) -> dict[str, Any]:
        return origin.model_dump(mode='json')

    @staticmethod
    def _row_to_origin(row: Any, origin_cls: type[DialogOrigin]) -> DialogOrigin:
        return origin_cls(**{name: row[name] for name in origin_cls.model_fields})

    @staticmethod
    def _find_origin_class(platform: str) -> type[DialogOrigin] | None:
        for origin_cls in ORIGIN_REGISTRY.values():
            fields = origin_cls.model_fields
            if 'platform' in fields and fields['platform'].default == platform:
                return origin_cls
        return None

    @classmethod
    async def save_event(cls, entry: DialogItem) -> int | None:
        db = await cls._get_db()

        origin_type = type(entry.origin)
        if origin_type.__name__ not in ORIGIN_REGISTRY:
            ORIGIN_REGISTRY[origin_type.__name__] = origin_type
        await cls._add_origin_columns(origin_type)

        origin_row = cls._origin_to_row(entry.origin)

        data = entry.model_dump(mode='json')
        data.pop('item_id')
        data.pop('origin')
        data['meta'] = json.dumps(data['meta'])

        all_cols = list(data.keys()) + list(origin_row.keys())
        quoted_cols = ', '.join(cls._quote_ident(c) for c in all_cols)
        placeholders = ', '.join(cls._placeholder(i) for i in range(1, len(all_cols) + 1))
        values = list(data.values()) + list(origin_row.values())

        return await cls._insert(
            db,
            f'INSERT INTO dialog_items ({quoted_cols}) VALUES ({placeholders}){cls._insert_returning_suffix()}',
            tuple(values),
        )

    @classmethod
    async def get_branch(cls, last_item_id: int) -> list[DialogItem]:
        db = await cls._get_db()

        rows = await cls._fetchall(db, f'''
            WITH RECURSIVE branch AS (
                SELECT * FROM dialog_items WHERE item_id = {cls._placeholder(1)}
                UNION ALL
                SELECT d.* FROM dialog_items d JOIN branch b ON d.item_id = b.previous_item_id
            )
            SELECT * FROM branch ORDER BY item_id
        ''', (last_item_id,))

        result: list[DialogItem] = []
        for row in rows:
            platform = row['platform']
            origin_cls = cls._find_origin_class(platform)
            if origin_cls is None:
                raise ValueError(f'Unknown origin platform: {platform!r}. '
                                 f'Ensure the corresponding plugin is imported.')
            origin = cls._row_to_origin(row, origin_cls)

            result.append(DialogItem(
                item_id=row['item_id'],
                content=row['content'],
                item_type=DialogItemType(row['item_type']),
                user=row['user'],
                role=DialogRole(row['role']),
                origin=origin,
                previous_item_id=row['previous_item_id'],
                external_id=row['external_id'],
                created_at=row['created_at'],
                meta=json.loads(row['meta']) if row['meta'] else {},
            ))
        return result

    @classmethod
    async def find_item_id_by_external_id(cls, external_id: str, origin: DialogOrigin) -> int | None:
        db = await cls._get_db()
        origin_row = cls._origin_to_row(origin)
        conditions = [f'external_id = {cls._placeholder(1)}']
        for i, col in enumerate(origin_row):
            conditions.append(f'{cls._quote_ident(col)} = {cls._placeholder(i + 2)}')
        values = [external_id] + list(origin_row.values())
        rows = await cls._fetchall(
            db, f'SELECT item_id FROM dialog_items WHERE {" AND ".join(conditions)}', tuple(values)
        )
        return rows[0]['item_id'] if rows else None

    @classmethod
    async def execute(cls, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        db = await cls._get_db()
        result = await cls._fetchall(db, query, params)
        await cls._commit(db)
        return result

    @classmethod
    async def close(cls) -> None:
        await cls._close()
