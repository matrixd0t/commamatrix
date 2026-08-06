# Plugin-Owned Tables

Use `BaseTable` when an extension needs structured persistent data. The row
schema is a Pydantic model; the table declaration is separate and does not
require an ORM.

```python
from pydantic import BaseModel

from commamatrix import BaseTable


class AuditRow(BaseModel):
    id: str
    event: str
    created_at: str


class AuditTable(BaseTable[AuditRow]):
    table_id = "audit.events"
    table_name = "audit_events"
    row_model = AuditRow
    primary_key = "id"
    indexes = (("event",),)
    unique_indexes = ()
    version = 1
```

`table_name` must be a valid SQL identifier. `table_id` is the stable logical
identity used for schema version tracking. Active table IDs and physical names
must not collide.

The declaration scanner validates the row model, primary key, autoincrement
field, indexes, and positive integer version. Define the actual table class at
module level and import its module from a package initializer.

## Migrations

Schema changes require an explicit version increase and a migration. The final
source declaration must retain all table attributes:

```python
class AuditTable(BaseTable[AuditRow]):
    table_id = "audit.events"
    table_name = "audit_events"
    row_model = AuditRow
    primary_key = "id"
    indexes = (("event",),)
    version = 2

    @classmethod
    async def migrate(cls, backend, from_version: int) -> None:
        if from_version < 2:
            await backend.add_column(
                cls.table_name,
                "source",
                "TEXT",
            )
```

Do not rely on Pydantic field changes to infer renames or destructive changes.
The backend applies the current version and rejects downgrades. Removing an
extension does not drop its table or data.

`TableManager` runs after the active `Storage` has been selected and before
ordinary plugin services start. A custom storage used with plugin tables must
expose a compatible `schema_backend`.

See [components/table.py](../../../components/table.py) and
[components/storage.py](../../../components/storage.py).

