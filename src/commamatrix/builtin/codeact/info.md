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
│                                  │                                │    └── <alias>*       │
└──────────────────────────────────┘                                └───────────────────────┘
```

## Protocol Constants (StrEnum)

All method name strings are defined as `StrEnum` in `protocol.py`:

| Enum | Members | Used in |
|---|---|---|
| `Namespace` | `TOOLS` | `_dispatch` top-level routing |
| `ToolsMethod` | `INVOKE`, `SEARCH`, `SCHEMAS`, `RESOLVE`, `ALIASES`, `LIST` | `_dispatch_tools` |

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
  "code": "import github\nawait github.list_issues(...)",
  "namespace": {"__name__": "__codeact__"},
  "timeout": 30.0,
  "tool_tree": {
    "github": {
      "__tools__": [
        {"id": "...", "name": "list_issues", "exported_name": "github.list_issues", "alias": "github", "doc": "...", "schema": {...}, "meta": {...}},
        ...
      ]
    }
  }
}
```

- Only **public** non-CodeAct tools (`meta.codeact` is falsy) appear in `tool_tree`.
- CodeAct-internal tools (`codeact.execute`, `codeact.search_tools`, `codeact.list_tools`) are excluded.
- Each tool entry includes `exported_name` — the canonical `alias.name` name used for invocation.

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
      task = create_task(handle_one_request(message))  # non-blocking
      pending_tasks.add(task)
  elif "result" in message or "error" in message:
      await wait_for_pending_tasks()
      return result
```

This allows multiple tool calls from a single `asyncio.gather()` in the worker to execute concurrently on the parent side.

## Method Namespace: `tools.*`

### `tools.invoke`

Execute an agent tool by its canonical `exported_name` through the full hook lifecycle.

**Request:**
```json
{
  "id": "t1",
  "method": "tools.invoke",
  "params": {
    "tool_call": {
      "tool_call_id": "",
      "tool_name": "github.list_issues",
      "tool_args": {"owner": "user", "repo": "repo"}
    }
  }
}
```

**Processing:**
1. Resolve `tool_name` via `ToolManager.resolve(exported_name)` — only matches `alias.name`
2. Verify tool is public (not a CodeAct-internal tool)
3. Construct `ToolCall` from params (uses `request.id` as default `tool_call_id`)
4. `CodeActService.invoke_tool()` → `Agent._run_tool_lifecycle()`
5. Output persistence is serialized per-run via `run.tool_output_lock`

**Response:**
```json
{"id": "t1", "result": "Search results: ..."}
```

### `tools.search`

Semantic search over public tool descriptions only.

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
{"id": "t2", "result": [{"id": "...", "namespace": "...", "alias": "github", "name": "list_issues", "exported_name": "github.list_issues", "doc": "...", "schema": {...}, "meta": {...}}, ...]}
```

### `tools.schemas`

Get all public tool schemas (no CodeAct-internal tools).

**Request:**
```json
{"id": "t3", "method": "tools.schemas", "params": {}}
```

**Response:**
```json
{"id": "t3", "result": [{"id": "...", "namespace": "...", "alias": "github", "name": "list_issues", "exported_name": "github.list_issues", "doc": "...", "schema": {...}, "meta": {...}}, ...]}
```

### `tools.resolve`

Resolve a canonical `alias.name` to its descriptor. Returns `null` for CodeAct-internal tools.

**Request:**
```json
{"id": "t4", "method": "tools.resolve", "params": {"name": "github.list_issues"}}
```

**Response (found):**
```json
{"id": "t4", "result": {"id": "...", "namespace": "...", "alias": "github", "name": "list_issues", "exported_name": "github.list_issues", "doc": "...", "schema": {...}, "meta": {...}}}
```

**Response (not found):**
```json
{"id": "t4", "result": null}
```

Resolution uses only canonical `alias.name` — no fallback to bare name, namespace, or descriptor ID.

### `tools.aliases`

List all available tool aliases (only those with at least one public tool).

**Request:**
```json
{"id": "t5", "method": "tools.aliases", "params": {}}
```

**Response:**
```json
{"id": "t5", "result": ["github", "fs", "filesystem"]}
```

### `tools.list`

List public tools within a specific alias.

**Request:**
```json
{"id": "t6", "method": "tools.list", "params": {"alias": "github"}}
```

**Response:**
```json
{"id": "t6", "result": [{"id": "...", "namespace": "...", "alias": "github", "name": "list_issues", "exported_name": "github.list_issues", "doc": "...", "schema": {...}, "meta": {...}}, ...]}
```

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

Each tool in a virtual module (`<alias>.<func_name>`) is an `async` proxy that calls the tool by its canonical `exported_name`:

```python
async def proxy(*args, **kwargs):
    bound = signature.bind(*args, **kwargs)
    bound.apply_defaults()
    return await client.request("tools.invoke", {"tool_call": {
        "tool_call_id": "", "tool_name": exported_name,  # e.g. "github.list_issues"
        "tool_args": dict(bound.arguments),
    }})
```

Note: `exported_name` is always `alias.name` (canonical). No `tool_id` is sent — resolution is by name only.

---

## Virtual Import Machinery

### Tool Module Creation

`make_tool_module(fullname, node, client)` creates virtual packages from `tool_tree`:

```
tool_tree = {
  "github": {                          → import github
    "__tools__": [{...}],               → github.list_issues, etc. (exported_name = github.list_issues)
    "sub": {                           → import github.sub
      "__tools__": [{...}]
    }
  }
}
```

Each tool's proxy uses `exported_name` from the descriptor, ensuring the parent receives the canonical `alias.name`.

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
        "exported_name": descriptor.exported_name,
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
Worker  →  Parent:  {"id": "y1", "method": "tools.invoke", "params": {"tool_call": {"tool_name": "github.list_issues", ...}}}
Worker  →  Parent:  {"id": "y2", "method": "tools.invoke", "params": {"tool_call": {"tool_name": "fs.read_file", ...}}}
                     (parent processes both concurrently)
Parent  →  Worker:  {"id": "y2", "result": "file content"}   (second completes first)
Parent  →  Worker:  {"id": "y1", "result": "issue list"}     (first completes second)
```

Responses are correlated by `id` — the `AsyncRPCClient` matches them to the correct `Future`, so `asyncio.gather()` returns correct results regardless of completion order.

### Pattern B: Virtual import + tool call

```python
# Worker executes:
import github
await github.list_issues(owner="user", repo="repo")

# Virtual import resolves github to a module from make_tool_module()
# github.list_issues is a proxy() function that calls:
client.request("tools.invoke", {"tool_call": {
    "tool_call_id": "", "tool_name": "github.list_issues",
    "tool_args": {"owner": "user", "repo": "repo"},
}})
```

### Pattern C: Concurrent tool calls

```python
# Worker executes — both tools run concurrently on parent:
results = await asyncio.gather(
    github.list_issues(owner="user", repo="repo"),
    fs.read_file(path="/tmp/data.txt"),
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
import github
await github.list_issues(owner="user", repo="repo")

import fs
await fs.read_file(path="/tmp/data.txt")

# All tools.* RPC methods are accessible as <alias>.<func_name>
# CodeAct-internal tools are NOT available (filtered by is_codeact_internal)
```

CodeAct control tools (`codeact.execute`, `codeact.search_tools`, `codeact.list_tools`) are never exposed to the worker — they are only visible to the external LLM.
