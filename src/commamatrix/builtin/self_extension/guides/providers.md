# Providers

Implement a provider only when the built-in provider is insufficient. Provider
slots have dedicated markers and managers; they are not ordinary `Service`
classes.

## Storage

A concrete `Storage` must implement:

```python
class MyStorage(Storage):
    async def save_event(self, entry: DialogItem) -> int | None: ...
    async def get_branch(self, last_item_id: int) -> list[DialogItem]: ...
    async def find_item_id_by_external_id(
        self,
        external_id: str,
        origin: DialogOrigin,
    ) -> int | None: ...
    async def get_history(
        self,
        *,
        origin_type=None,
        origin_fields=None,
    ) -> list[DialogItem]: ...
```

The active storage is selected with `active_storage`, using a provider
descriptor ID, or falls back to the first available provider. Storage providers
may also expose `schema_backend` for plugin-owned tables.

## FileStorage

A concrete `FileStorage` implements `save(data, ext)`, `get(file_id)`, and
`delete(file_id)`. It should return stable file IDs and reject unsafe path-like
IDs. Its `url()` normally delegates to the agent HTTP server.

## LLMAdapter

A concrete `LLMAdapter` implements `refresh_llms()` and returns an async
iterator from `ask_llm(ctx, stream=False)`. The iterator yields complete
`LLMResponseBlock` values and finishes with `StreamEnd`. When streaming, it may
also yield `StreamDelta` values for realtime delivery.

Use the existing text, reasoning, image, file, and tool-call block classes. Keep
provider-specific wire data under response or item metadata so replay and
protocol-specific round trips remain possible.

The default model selection filters by the `agentic_model` substring when it is
set, then selects the available model with the lowest input-token cost. A hook
can change the selected adapter or model before a call.

Provider classes must be concrete, top-level subclasses of their respective
provider base classes. Read the relevant base class before implementing one.

See [components/storage.py](../../../components/storage.py),
[components/file_storage.py](../../../components/file_storage.py), and
[components/llm_adapter.py](../../../components/llm_adapter.py).

