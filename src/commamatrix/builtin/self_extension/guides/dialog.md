# Dialog and Origins

`DialogOrigin` identifies a conversation on a platform. Subclass it with the
fields required to address that conversation. Origins are frozen Pydantic models
and concrete subclasses are registered for deserialization.

```python
from commamatrix import DialogOrigin


class MyForumTopicOrigin(DialogOrigin):
    origin_type: str = "my_forum_topic"
    platform: str = "my_forum"
    topic_id: str
```

`DialogItem` is the persisted unit of conversation history. Its important fields
are `content`, `item_type`, `role`, `origin`, `user`, `previous_item_id`,
`external_id`, `created_at`, and `meta`.

## Item Types

`DialogItemType` contains:

- `INPUT`
- `IMAGE_INPUT`
- `FILE_INPUT`
- `OUTPUT`
- `IMAGE_OUTPUT`
- `FILE_OUTPUT`
- `TOOL_CALL`
- `TOOL_CALL_RESULT`
- `REASONING`

`DialogRole` contains `SYSTEM`, `DEVELOPER`, `USER`, `ASSISTANT`, and `TOOL`.

Items form a branch through `previous_item_id`. Connectors can provide a
`previous_external_id`; the agent resolves it through storage before starting a
run. An external ID is platform-specific and may be absent even when the item
is persisted.

## Persistence Semantics

Input items are persisted before the LLM call. Output, reasoning, tool-call, and
tool-result items pass through the connector and storage pipeline. A complete
LLM response is delivered before its tool calls execute.

Instructions are temporary system items and are not ordinary persisted history.
`RunCtx.chain_state` is copied to `DialogItem.meta["chain"]` and restored from
the latest item in a branch. Use it for small serializable cross-message state;
use `RunCtx.state` for per-run state.

## Media

`DialogItem.content` is text. Binary content should normally be stored through
`FileStorage` and referenced by file ID or URL. LLM response image and file
blocks carry a reference and extension, while connectors decide how to render
them for their platform.

See [components/dialog.py](../../../components/dialog.py),
[components/llm_adapter.py](../../../components/llm_adapter.py), and
[components/file_storage.py](../../../components/file_storage.py).

