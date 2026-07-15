# CodeAct RPC Protocol

## Architecture

```
┌──────────────────────────────────┐          stdin/stdout          ┌───────────────────────┐
│  Parent Process (Agent)          │    ─────── JSON/NDJSON ────→   │  Child Process        │
│                                  │                                │  (Python worker)      │
│  SubprocessBackend               │    ←────────────────────────   │                       │
│    ├── asyncio subprocess        │                                │  _RPCClient           │
│    └── RPCServer                 │                                │    ├── call()         │
│          ├── _dispatch_context() │                                │    └── acall()        │
│          ├── _dispatch_storage() │                                │                       │
│          └── _dispatch_tools()   │                                │  Virtual modules      │
│                                  │                                │    ├── context        │
│                                  │                                │    └── <alias>*       │
└──────────────────────────────────┘                                └───────────────────────┘
```

## Protocol Constants (StrEnum)

All method name strings are defined as `StrEnum` in `protocol.py`:

| Enum | Members | Used in |
|---|---|---|
| `Namespace` | `CONTEXT`, `TOOLS` | `_dispatch` top-level routing |
| `ContextField` | `RUN`, `TOOL_CALL`, `META`, `STORAGE` | `_dispatch_context` |
| `StorageMethod` | `SAVE_EVENT`, `GET_BRANCH`, `FIND_ITEM_ID_BY_EXTERNAL_ID` | `_dispatch_storage` |
| `ToolsMethod` | `INVOKE`, `SEARCH`, `SCHEMAS`, `RESOLVE`, `ALIASES`, `LIST` | `_dispatch_tools` |

Dispatch on the server uses `match/case` with enum comparison — the same wire format strings are sent by the worker, and matched by value.

## Context Tree (accessible from worker code)

The `context` module is the worker's window into the parent agent state. Every attribute is a lazy `_RemoteValue` that issues an RPC call on access.

```
context
├── run                          # RunCtx — current agentic loop state
│   ├── run_id                   # str — unique UUID per run
│   ├── iteration                # int — tool loop counter (0-based)
│   ├── user                     # str — user identifier
│   ├── origin                   # DialogOrigin — platform + chat/scene IDs
│   │   ├── platform             # str (e.g. "telegram", "cli")
│   │   └── ...                  # subclass-specific fields
│   ├── connector                # Connector | None — platform adapter
│   │   └── __class__.__name__   # str (e.g. "CliConnector")
│   ├── state                    # dict[str, Any] — mutable hook scratchpad
│   └── agent                    # Agent — (serialized, agent field stripped)
│       ├── config               # Config — agent config dict
│       └── ...                  # other Agent properties
│
├── tool_call                    # ToolCall — the tool being executed
│   ├── tool_call_id             # str
│   ├── tool_name                # str
│   └── tool_args                # dict[str, Any]
│
├── meta                         # dict[str, Any] — hook-injectable metadata
│
├── storage                      # Storage methods (proxied to active storage)
│   ├── save_event(item)         # → int (item_id)
│   ├── get_branch(last_item_id) # → list[dict]
│   └── find_item_id_by_external_id(external_id, origin)
│                                # → int | None
│
└── tools                        # High-level tool accessor
    ├── invoke(tool_name, args, tool_id)  # → any (serialized result)
    └── search(query, limit=5)            # → list[dict]
```

**Resolution rules** (`_resolve_path` in server.py):
- Dotted path segments traverse `getattr()` on objects or `get()` on dicts
- `None` at any step short-circuits and returns `None`
- `context.run.agent` is serialized but the `agent` field is stripped to avoid circular references (the worker should not drill into agent internals)

**Usage in worker code:**
```python
run_id = await context.run.run_id               # → "a1b2c3d4..."
user = await context.run.user                   # → "user123"
args = await context.tool_call.tool_args        # → {"query": "..."}
await context.storage.save_event({"item_type": "text", ...})
result = await context.tools.invoke("search_web", {"query": "python"})
```

## Transport

- **Medium**: stdin/stdout pipes of a child Python process
- **Encoding**: UTF-8
- **Framing**: Newline-delimited JSON (NDJSON) — one JSON object per line
- **Bidirectional**: Both parent→child and child→parent use the same format

## Messages

### RPC Request

```python
@dataclass(slots=True, kw_only=True)
class RPCRequest:
    id: str                          # Unique request ID (uuid hex)
    method: str                      # Dotted method path, e.g. "tools.invoke"
    params: dict[str, Any]           # Positional/keyword args
```

JSON wire format:

```json
{"id": "a1b2c3", "method": "tools.invoke", "params": {"tool_call": {...}}}
```

### RPC Response (success)

```python
@dataclass(slots=True, kw_only=True)
class RPCResponse:
    id: str
    result: Any = None
    error: RPCError | None = None
```

JSON wire format:

```json
{"id": "a1b2c3", "result": ...}
```

### RPC Response (error)

```python
class RPCError(Exception):
    code: int                        # JSON-RPC-style error code
    message: str                     # Human-readable error
    data: Any = None                 # Optional extra info
```

JSON wire format:

```json
{"id": "a1b2c3", "error": {"code": -32601, "message": "Unknown method"}}
```

### Error codes

| Code    | Meaning          | Source                   |
|---------|------------------|--------------------------|
| -32600  | Invalid request  | Empty method / path      |
| -32601  | Method not found | Unknown namespace/method |
| -32602  | Invalid params   | Wrong type, missing key  |
| -32603  | Internal error   | Unhandled exception      |

---

## Boot Sequence (parent → child)

The **first message** from parent to child is NOT an RPC call. It is a one-shot payload that carries the code and environment:

```json
{
  "code": "import github\nawait github.list_issues(...)",
  "namespace": {"__name__": "__codeact__"},
  "timeout": 30.0,
  "tool_tree": {
    "github": {
      "__tools__": [
        {"id": "...", "name": "list_issues", "namespace": "my_plugin.tools", "alias": "github", "doc": "...", "schema": {...}, "metadata": {...}},
        ...
      ],
      "sub_namespace": {
        "__tools__": [...]
      }
    },
    "fs": {
      "__tools__": [...]
    }
  }
}
```

The child deserializes this in `worker.py:main()`, sets up virtual modules from `tool_tree`, and begins executing `code`.

---

## Shutdown Sequence (child → parent)

After code execution, the child sends a **single result message** (not wrapped in an RPC call):

```json
{
  "id": "",
  "result": {
    "stdout": "...output...",
    "stderr": "...errors...",
    "returncode": 0,
    "elapsed": 123.45
  }
}
```

This terminates the RPC cycle — the child process exits after writing this.

---

## RPC Loop (child → parent during execution)

While the child executes code, it may call back to the parent for:
- Reading `context.*` fields
- Invoking tools (`tools.*`)
- Storage operations (`context.storage.*`)

The parent's `SubprocessBackend` loops on `transport.recv()`, dispatching each message through `RPCServer.handle()`:

```
transport.recv() → message
  if "method" in message:
      response = await server.handle(message)
      await transport.send(response)
  elif "result" in message or "error" in message:
      # Execution complete, break
```

---

## Method Namespace: `context.*`

Accesses fields of `BeforeToolCallCtx` provided to the backend.

### `context.run.<attr>[.<attr>...]`

Resolves an arbitrary attribute chain on `RunCtx` via `_resolve_path()`. Supports dict access on intermediate objects.

**Request:**
```json
{"id": "r1", "method": "context.run.agent.config.active_storage", "params": {}}
```

**Response:**
```json
{"id": "r1", "result": "sqlite"}
```

**Resolution logic** (`_resolve_path`):
```python
for part in path:
    if isinstance(obj, dict):
        obj = obj.get(part)
    else:
        obj = getattr(obj, part, None)
    if obj is None:
        return None
return _make_serializable(obj)
```

### `context.tool_call.<attr>[.<attr>...]`

Attribute chain on the current `ToolCall`.

**Request:**
```json
{"id": "r2", "method": "context.tool_call.tool_name", "params": {}}
```

**Response:**
```json
{"id": "r2", "result": "execute"}
```

### `context.meta.<attr>[.<attr>...]`

Attribute chain on `ctx.meta` (arbitrary metadata dict set by hooks).

**Request:**
```json
{"id": "r3", "method": "context.meta.codeact_enabled", "params": {}}
```

### `context.storage.<method>`

Storage operations — proxied to `agent.storage`.

**Request:**
```json
{"id": "s1", "method": "context.storage.save_event", "params": {"item": {"item_type": "text", ...}}}
```

Supported methods:

| Method                        | Parameters                                      | Returns     |
|-------------------------------|-------------------------------------------------|-------------|
| `save_event`                  | `item` (dict → DialogItem)                      | int (id)    |
| `get_branch`                  | `last_item_id` (int)                            | list[dict]  |
| `find_item_id_by_external_id` | `external_id` (str), `origin` (dict → Origin)   | int \| None |

**Params resolution:** `_call_arguments` checks for `args`/`kwargs` keys in the params dict, else treats the entire params dict as kwargs.

```python
def _call_arguments(params):
    if "args" in params or "kwargs" in params:
        return list(params.get("args", [])), dict(params.get("kwargs", {}))
    return [], dict(params)
```

---

## Method Namespace: `tools.*`

### `tools.invoke`

Execute an agent tool by name through the full hook lifecycle.

**Request:**
```json
{
  "id": "t1",
  "method": "tools.invoke",
  "params": {
    "tool_call": {
      "tool_call_id": "",
      "tool_name": "search_web",
      "tool_args": {"query": "python"},
      "tool_id": ""
    }
  }
}
```

**Processing:**
1. Construct `ToolCall` from params (uses `request.id` as default `tool_call_id`)
2. `ctx.run.agent.services.require(CodeActManager)` → `CodeActManager.invoke_tool()`
3. `invoke_tool()` calls `ctx.run.agent._run_tool_lifecycle(ctx, tool_call)`
4. Result is serialized via `to_jsonable()`

**Response:**
```json
{"id": "t1", "result": "Search results: ..."}
```

### `tools.search`

Semantic search over tool descriptions.

**Request:**
```json
{
  "id": "t2",
  "method": "tools.search",
  "params": {"query": "search web async", "limit": 5}
}
```

**Response:**
```json
{"id": "t2", "result": [{"namespace": "...", "name": "...", "doc": "...", ...}, ...]}
```

### `tools.schemas`

Get all tool schemas (for code generation/introspection).

**Request:**
```json
{"id": "t3", "method": "tools.schemas", "params": {}}
```

**Response:**
```json
{"id": "t3", "result": [{"namespace": "...", "name": "...", "schema": {...}}, ...]}
```

### `tools.resolve`

Resolve a tool name to its descriptor.

**Request:**
```json
{"id": "t4", "method": "tools.resolve", "params": {"name": "my_tool"}}
```

**Response (found):**
```json
{"id": "t4", "result": {"id": "...", "namespace": "...", "alias": "...", "name": "...", "doc": "...", "schema": {...}}}
```

**Response (not found):**
```json
{"id": "t4", "result": null}
```

### `tools.aliases`

List all available tool module aliases (namespaces).

**Request:**
```json
{"id": "t5", "method": "tools.aliases", "params": {}}
```

**Response:**
```json
{"id": "t5", "result": ["github", "fs", "filesystem"]}
```

### `tools.list`

List tools within a specific alias.

**Request:**
```json
{"id": "t6", "method": "tools.list", "params": {"alias": "github"}}
```

**Response:**
```json
{"id": "t6", "result": [{"id": "...", "name": "list_issues", "doc": "...", "schema": {...}, "metadata": {...}}, ...]}
```

---

## Client-Side Proxy Objects (worker.py)

### `_RPCClient`

Synchronous `call()` and async `acall()` for issuing requests. Thread-safe (one mutex). Calls block the worker thread and wait for a matching response.

```python
class _RPCClient:
    def call(self, method, params=None):
        # serialize → write → flush → read → deserialize
        # raises RuntimeError on error response

    async def acall(self, method, params=None):
        return await asyncio.to_thread(self.call, method, params)
```

### `_RemoteValue`

Lazy, chainable proxy that builds dotted paths:

```python
class _RemoteValue:
    def __getattr__(self, name: str) -> _RemoteValue:  # appends ".name" to path
    def __call__(self, *args, **kwargs) -> _RemoteCall:  # creates awaitable call
    def __await__(self):  # awaits acall(path) directly (no arguments)
```

Pattern: `context.run.user` → `_RemoteValue(client, "context.run.user")` → when awaited, calls `client.acall("context.run.user")`.

### `_RemoteCall`

Holds arguments for a remote call, sends on await:

```python
class _RemoteCall:
    def __await__(self):  # client.acall(path, {"args": ..., "kwargs": ...})
```

### `_ToolsAccessor`

High-level accessor with named methods:

```python
class _ToolsAccessor:
    async def invoke(self, tool_name, args=None, tool_id="")  # → tools.invoke
    async def search(self, query, limit=5)                    # → tools.search
```

---

## Virtual Import Machinery

### Module Creation

`make_context(client)` creates the `context` module with fixed attributes:

| Attribute     | Type            | Path sent to parent         |
|---------------|-----------------|-----------------------------|
| `run`         | `_RemoteValue`  | `context.run`               |
| `tool_call`   | `_RemoteValue`  | `context.tool_call`         |
| `meta`        | `_RemoteValue`  | `context.meta`              |
| `storage`     | `_RemoteValue`  | `context.storage`           |
| `tools`       | `_ToolsAccessor` | (wraps `tools.invoke`, `tools.search`) |

### Tool Module Creation

`make_context_module(fullname, node, client)` creates virtual packages from `tool_tree`:

```
tool_tree = {
  "github": {                          → import github
    "__tools__": [{...}],               → github.list_issues, etc.
    "sub": {                           → import github.sub
      "__tools__": [{...}]
    }
  }
}
```

Each tool in `__tools__` gets a `_make_tool_proxy(client, descriptor)` created with a `inspect.Signature` reconstructed from JSON Schema + metadata.

### Import Hook

A `MetaPathFinder` + `_Loader` pair intercepts `import` for any module name registered in `_factories`. Modules are cached in `_modules_cache` to avoid re-creation.

```python
sys.meta_path.insert(0, _Finder())  # installed before code execution
```

### Tool Proxy Function

```python
async def proxy(*args, **kwargs):
    bound = signature.bind(*args, **kwargs)
    bound.apply_defaults()
    return await client.acall("tools.invoke", {
        "tool_call": {"tool_call_id": "", "tool_name": name, "tool_args": dict(bound.arguments), "tool_id": tool_id}
    })
```

---

## Serialization

Both parent and child serialize responses through the same logic:

| Type                     | Serialized as                    |
|--------------------------|----------------------------------|
| `None`                   | `None`                           |
| `str`, `int`, `float`, `bool` | As-is                      |
| `Enum`                   | `.value`                         |
| `dict`                   | keys → str, values → recurse     |
| `list`, `tuple`, `set`   | list, element → recurse          |
| Pydantic model           | `.model_dump(mode="json")`       |
| dataclass                | `field.name` → value dict        |
| object with `__dict__`   | non-underscore attributes dict   |
| everything else          | `str(obj)`                       |

Note: `_make_serializable` (server.py) and `to_jsonable` (api/utils.py) share the same logic but are separate implementations.

---

## Data Flow Patterns

### Pattern A: Simple attribute read

```
Worker  →  Parent:  {"id": "x", "method": "context.run.user"}
Parent  →  Worker:  {"id": "x", "result": "user123"}
```

### Pattern B: Tool invocation

```
Worker  →  Parent:  {"id": "y", "method": "tools.invoke", "params": {"tool_call": {...}}}
Parent  →  Parent:  CodeActManager.invoke_tool() → Agent._run_tool_lifecycle() → ToolManager.call()
Parent  →  Worker:  {"id": "y", "result": "result string"}
```

### Pattern C: Remote call with arguments

```
Worker  →  Parent:  {"id": "z", "method": "context.storage.save_event", "params": {"args": [item_data], "kwargs": {}}}
Parent  →  Parent:  storage.save_event(_parse_dialog_item(item_data))
Parent  →  Worker:  {"id": "z", "result": 42}
```

### Pattern D: Virtual import + tool call

```python
# Worker executes:
import github
await github.list_issues(owner="user", repo="repo")

# Virtual import resolves github to a module from make_context_module()
# github.list_issues is a proxy() function that calls:
client.acall("tools.invoke", {"tool_call": {
    "tool_call_id": "", "tool_name": "list_issues",
    "tool_args": {"owner": "user", "repo": "repo"},
    "tool_id": "..."}
})
```


