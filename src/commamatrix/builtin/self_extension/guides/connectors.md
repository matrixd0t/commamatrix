# Connectors

A connector translates an external platform into `DialogItem` objects and
renders complete outgoing items back to that platform.

Define a platform-specific immutable `DialogOrigin` and a generic connector:

```python
from commamatrix import (
    Connector,
    DialogItem,
    DialogItemType,
    DialogOrigin,
    DialogRole,
    OnParsedCtx,
    RunCtx,
)


class ChatOrigin(DialogOrigin):
    origin_type: str = "my_chat"
    platform: str = "my_chat"
    chat_id: str


class ChatConnector(Connector[ChatOrigin]):
    async def parse(self, data: dict) -> OnParsedCtx | None:
        if data.get("platform") != "my_chat":
            return None
        origin = ChatOrigin(chat_id=str(data["chat_id"]))
        item = DialogItem(
            content=str(data["content"]),
            item_type=DialogItemType.INPUT,
            role=DialogRole.USER,
            origin=origin,
            user=str(data.get("user", "unknown")),
        )
        return OnParsedCtx(
            agent=self.agent,
            connector=self,
            raw=data,
            dialog_items=[item],
            previous_external_id=data.get("previous_external_id"),
        )

    async def send(self, run: RunCtx, item: DialogItem) -> str:
        if not isinstance(run.origin, ChatOrigin):
            return ""
        # Render item according to item.item_type and send it.
        return "my-chat-message-id"

    async def get_user_name(self, origin: DialogOrigin) -> str | None:
        if isinstance(origin, ChatOrigin):
            return None
        return None

    async def listen(self, on_recv) -> None:
        # Read platform events and call await on_recv(raw_event).
        return
```

`parse()`, `send()`, and `get_user_info()` are required for a concrete
connector. The generic argument lets the framework infer the connector's
`origin_types`.

## Resolution

Every discovered connector is active. When an origin is used, the framework
requires exactly one connector whose `origin_types` contains that origin type.
Zero or multiple matches raise `LookupError`; do not register overlapping
connectors accidentally.

The base connector starts `listen(self.agent.handle)` as a task. Override
`listen()` for polling, webhook adapters, or another event loop. Override
`start()` and `stop()` only when the external client needs additional lifecycle
handling, and always stop listeners and owned clients.

`send()` receives the complete `RunCtx` and every outgoing block, including text,
reasoning, images, files, and tool calls. Return an external ID when the platform
provides one, or an empty string when it does not. The agent persists the item
even when delivery returns no external ID.

## Streaming

Set `supports_streaming = True` and implement `send_stream_chunk()` only when the
platform supports partial updates. `StreamDelta` values are realtime delivery
events, not ordinary dialog history. The complete response blocks still pass
through `send()` and persistence.

See [components/connector.py](../../../components/connector.py),
[components/dialog.py](../../../components/dialog.py), and the built-in
[HTTP connector](../../http_connector/connector.py).

