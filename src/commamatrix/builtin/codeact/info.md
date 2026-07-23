# CodeAct RPC Protocol

## Architecture

```
┌──────────────────────────────────┐       loopback TCP/NDJSON      ┌───────────────────────┐
│  Parent Process (Agent)          │    ─────── JSON/NDJSON ────→   │  Child Process        │
│                                  │                                │  (Python worker)      │
│  SubprocessBackend               │    ←────────────────────────   │                       │
│    ├── asyncio subprocess        │                                │  AsyncRPCClient       │
│    └── RPCServer (stateless)     │                                │    ├── request()      │
│          └── concurrent dispatch │                                │    └── read_responses │
│                                  │                                │                       │
│                                  │                                │  Virtual modules      │
│                                  │                                │    └── tools.<alias>* │
└──────────────────────────────────┘                                └───────────────────────┘
```

## Protocol Constants (StrEnum)

All method name strings are defined as `StrEnum` in `protocol.py`:

| Enum | Members | Used in |
|---|---|---|
| `Namespace` | `TOOLS` | `_dispatch` top-level routing |
| `ToolsMethod` | `INVOKE`, `RESOLVE` | `_dispatch_tools` |

Dispatch on the server uses `match/case` with enum comparison.

## Transport

- **Medium**: authenticated TCP connection bound to `127.0.0.1`
- **Encoding**: UTF-8
- **Framing**: Newline-delimited JSON (NDJSON) — one JSON object per line
- **Handshake**: worker sends a one-time token; the server replies with `hello_ok`
- **Bidirectional**: Both parent→child and child→parent use the same format
- **Concurrency**: `TcpTransport.send()` uses `asyncio.Lock` to prevent interleaving of concurrent frames
- **Write lock**: Only protects framing — tool execution is not serialized
- **Reuse**: `TcpTransport` and `TcpServer` are shared by subprocess, Docker and Systemd backends

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
{"id": "a1b2c3", "method": "tools.invoke", "params": {"tool_id": "python://mod/func", "tool_args": {"x": 1}, "tool_call_id": ""}}
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
| -32001  | RPC timeout      | Per-call timeout exceeded |
| -32002  | RPC cancelled    | Parent cancelled request  |
| -32600  | Invalid request  | Empty method / path       |
| -32601  | Method not found | Unknown namespace/method  |
| -32602  | Invalid params   | Tool not found, ambiguity |
| -32603  | Internal error   | Unhandled exception       |

---

## Boot Sequence (parent → child)

After the TCP handshake, the first message from parent to child is NOT an RPC call. It is a one-shot payload that carries the code and environment:

```json
{
  "code": "import tools.github\nawait tools.github.list_issues(...)",
  "namespace": {"__name__": "__codeact__"},
  "timeout": 30.0,
  "rpc_timeout": 10.0,
  "tool_tree": {
    "tools": {
      "github": {
        "__tools__": [
          {"id": "...", "name": "list_issues", "alias": "github", "doc": "...", "schema": {...}, "meta": {...}},
          ...
        ]
      }
    }
  }
}
```

- Only **public** tools appear in `tool_tree` — CodeAct-internal tools (those with `visible_in_codeact=True, visible_outside_codeact=False`) are excluded via `is_codeact_internal()`.
- Control tools (`execute`, `search_tools`, `list_tools`, `exit_codeact`) are never exposed to the worker.
- Tools are available both under `tools.<alias>.<name>` and, when the name is a valid identifier, as a callable `tools.<name>` module. This supports `import tools.echo as echo; await echo(...)`.
- Tool invocation on the worker side uses the descriptor `id` for direct resolution.

The child reads this asynchronously, sets up virtual modules from `tool_tree`, and begins executing `code`.

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

While the child executes code, it may call back to the parent for invoking tools (`tools.*`).

The parent's `SubprocessBackend` handles RPC requests **concurrently** — each incoming request spawns a separate `asyncio.Task`:

```
transport.recv() → message
  if "method" in message:
      task = create_task(_handle_rpc(message))  # non-blocking
      pending_tasks.add(task)
  elif message.get("type") == "execution_result":
      response_data = message
      break
```

This allows multiple tool calls from a single `asyncio.gather()` in the worker to execute concurrently on the parent side.

## Method Namespace: `tools.*`

### `tools.invoke`

Execute an agent tool by its descriptor `id` through the full hook lifecycle.

**Request:**
```json
{
  "id": "t1",
  "method": "tools.invoke",
  "params": {
    "tool_id": "python://mod/func",
    "tool_args": {"owner": "user", "repo": "repo"},
    "tool_call_id": ""
  }
}
```

**Processing:**
1. Resolve `tool_id` via `ToolManager.resolve_id(id)` — direct descriptor lookup
2. Verify tool is public (not CodeAct-internal via `is_codeact_internal()`)
3. Construct `ToolCall` from params
4. `CodeActService.invoke_tool()` → `Agent._run_tool_lifecycle()`

**Response:**
```json
{"id": "t1", "result": "Search results: ..."}
```

### `tools.resolve`

Resolve a canonical `alias.name` to its descriptor. Returns `null` for unknown or CodeAct-internal tools.

**Request:**
```json
{"id": "t4", "method": "tools.resolve", "params": {"name": "github.list_issues"}}
```

**Response (found):**
```json
{"id": "t4", "result": {"id": "...", "namespace": "...", "alias": "github", "name": "list_issues", "doc": "...", "schema": {...}, "meta": {...}}}
```

**Response (not found or internal):**
```json
{"id": "t4", "result": null}
```

Resolution uses only canonical `alias.name` — no fallback to bare name, namespace, or descriptor ID.

---

## Client-Side Proxy Objects (worker.py)

### `AsyncRPCClient`

Fully async with `asyncio.Lock` only for write framing. No `threading.Lock` or blocking reads.

```python
class AsyncRPCClient:
    async def request(self, method, params=None):
        # Creates Future, sends NDJSON, waits for matching response
        # Supports concurrent pending requests via request ID correlation

    async def read_responses(self):
        # Background reader task: matches responses to Futures by request ID
        # Runs as a separate asyncio Task alongside user code
```

Key design:
- Each `request()` creates a unique ID and a `Future`
- The `read_responses()` task maps incoming responses to the correct Future by ID
- Multiple `request()` calls can be made concurrently — responses are matched independently
- `asyncio.Lock` on write prevents concurrent writes from interleaving bytes in the TCP stream

### Tool Proxy Function

Each tool in a virtual module (`tools.<alias>.<func_name>`) is an `async` proxy that calls the tool by its descriptor `id`:

```python
async def proxy(*args, **kwargs):
    bound = signature.bind(*args, **kwargs)
    bound.apply_defaults()
    return await client.request("tools.invoke", {
        "tool_id": tool_id,  # descriptor.id for direct resolution
        "tool_args": dict(bound.arguments),
        "tool_call_id": "",
    })
```

Note: Resolution on the server side is by `tool_id` (descriptor ID), not by name.

---

## Virtual Import Machinery

### Tool Module Creation

`make_tool_module(fullname, node, client)` creates virtual packages from `tool_tree`:

```
tool_tree = {
  "tools": {
    "github": {                        → import tools.github
      "__tools__": [{...}],             → tools.github.list_issues, etc.
      "sub": {                         → import tools.github.sub
        "__tools__": [{...}]
      }
    }
  }
}
```

All tool aliases are nested under the `"tools"` key. The worker creates a root `tools` package and registers each alias as `tools.<alias>`. Code inside `execute()` imports tools as `import tools.<name> as <name>`.

Each tool's proxy uses the descriptor `id` for direct RPC resolution.

### Import Hook

A `MetaPathFinder` + `_Loader` pair intercepts `import` for any module name registered in `_factories`. Modules are cached in `_modules_cache` to avoid re-creation.

```python
sys.meta_path.insert(0, _Finder())  # installed before code execution
```

---

## Serialization

### Tool Descriptor Wire Format

All RPC introspection methods use explicit serializers:

```python
def serialize_tool_descriptor(descriptor):
    return {
        "id": descriptor.id,
        "namespace": descriptor.namespace,
        "alias": descriptor.alias,
        "name": descriptor.name,
        "doc": descriptor.doc,
        "schema": descriptor.schema,
        "meta": descriptor.meta,       # not "metadata"
    }
```

Only these fields are transmitted — internal fields like `_source_ref` are excluded.

### Result Serialization

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

No runtime objects are leaked — `agent`, `Service`, and `Source` instances are never serialized.

---

## Data Flow Patterns

### Pattern A: Concurrent tool invocation

```
Worker  →  Parent:  {"id": "y1", "method": "tools.invoke", "params": {"tool_id": "python://github/list_issues", "tool_args": {"owner": "user", "repo": "repo"}}}
Worker  →  Parent:  {"id": "y2", "method": "tools.invoke", "params": {"tool_id": "python://fs/read_file", "tool_args": {"path": "/tmp/data.txt"}}}
                     (parent processes both concurrently)
Parent  →  Worker:  {"id": "y2", "result": "file content"}   (second completes first)
Parent  →  Worker:  {"id": "y1", "result": "issue list"}     (first completes second)
```

Responses are correlated by `id` — the `AsyncRPCClient` matches them to the correct `Future`, so `asyncio.gather()` returns correct results regardless of completion order.

### Pattern B: Virtual import + tool call

```python
# Worker executes:
import tools.github
await tools.github.list_issues(owner="user", repo="repo")

# Virtual import resolves tools.github to a module from make_tool_module()
# tools.github.list_issues is a proxy() function that calls:
client.request("tools.invoke", {
    "tool_call_id": "", "tool_id": "<descriptor_id>",
    "tool_args": {"owner": "user", "repo": "repo"},
})
```

### Pattern C: Concurrent tool calls

```python
# Worker executes — both tools run concurrently on parent:
results = await asyncio.gather(
    tools.github.list_issues(owner="user", repo="repo"),
    tools.fs.read_file(path="/tmp/data.txt"),
)
```

---

## Stateless Execution Model

Each `await codeact.execute(code, ctx)` call:
- Creates a **new subprocess**
- Creates a **new namespace**
- Creates a **new RPC client/server** pair
- Creates a **new set of virtual modules**
- Has its own **timeout scope**

No state is preserved between executions. Data persistence is via `Storage`, `FileStorage`, or tools.

```python
await execute("x = 10")
await execute("print(x)")  # → NameError: name 'x' is not defined
```

---

## Timeout and Cancellation

| Scenario | Behavior |
|---|---|
| Code execution timeout | Worker is terminated via `terminate()` → `kill()`; `ExecutionResult` with `returncode=124` |
| RPC call timeout | Worker receives RPC error `-32001` |
| Parent cancellation | Worker transport is closed; remaining RPC Futures get `CancelledError` |
| Graceful shutdown | `terminate()` sent first; after `shutdown_timeout`, `kill()` is used |
| Large stderr | Read concurrently, truncated at `max_output_bytes` |
| Large stdout | Truncated at `max_output_bytes` |

No child process is left alive after any of these scenarios — `_cleanup()` guarantees process reaping.

---

## Sandbox Capabilities (from worker code)

The sandbox has **no** `context` module — the only way to interact with the parent is through virtual tool modules:

```python
# Import any tool alias registered in tool_tree
import tools.github
await tools.github.list_issues(owner="user", repo="repo")

import tools.fs
await tools.fs.read_file(path="/tmp/data.txt")

# All tools.* RPC methods are accessible as tools.<alias>.<func_name>
# CodeAct-internal tools are NOT available (filtered by is_codeact_internal)
```

CodeAct control tools (\execute\, \search_tools\, \list_tools\, \exit_codeact\) are never exposed to the worker  they have \isible_in_codeact=True, visible_outside_codeact=False\ and are filtered out by \is_codeact_internal()\. Additionally, \enable_codeact\ (with \isible_in_codeact=False\) is also filtered out, preventing the worker from calling it via virtual import.
