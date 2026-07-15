# CodeAct RPC Protocol

## Architecture

```
┌──────────────────────────────────┐          stdin/stdout          ┌───────────────────────┐
│  Parent Process (Agent)          │    ─────── JSON/NDJSON ────→   │  Child Process        │
│                                  │                                │  (Python worker)      │
│  SubprocessBackend               │    ←────────────────────────   │                       │
│    ├── asyncio subprocess        │                                │  _RPCClient           │
│    └── RPCServer                 │                                │    ├── call()         │
│          └── _dispatch_tools()   │                                │    └── acall()        │
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

CodeAct-internal tools (`@tool(codeact=True)` — `execute`, `search_tools`, `list_tools`) are **stripped** from `tool_tree` by `_strip_codeact_tools()` and cannot be invoked from inside the sandbox.

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

While the child executes code, it may call back to the parent for invoking tools (`tools.*`).

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
2. `ctx.run.agent.services.require(CodeActService)` → `CodeActService.invoke_tool()`
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

### Tool Proxy Function

Each tool in a virtual module (`<alias>.<func_name>`) is an `async` proxy that reconstructs `inspect.Signature` from JSON Schema, binds arguments, and calls `client.acall("tools.invoke", ...)`:

```python
async def proxy(*args, **kwargs):
    bound = signature.bind(*args, **kwargs)
    bound.apply_defaults()
    return await client.acall("tools.invoke", {
        "tool_call": {"tool_call_id": "", "tool_name": name, "tool_args": dict(bound.arguments), "tool_id": tool_id}
    })
```

---

## Virtual Import Machinery

### Tool Module Creation

`make_tool_module(fullname, node, client)` creates virtual packages from `tool_tree`:

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

### Pattern A: Tool invocation

```
Worker  →  Parent:  {"id": "y", "method": "tools.invoke", "params": {"tool_call": {...}}}
Parent  →  Parent:  CodeActService.invoke_tool() → Agent._run_tool_lifecycle() → ToolManager.call()
Parent  →  Worker:  {"id": "y", "result": "result string"}
```

### Pattern B: Virtual import + tool call

```python
# Worker executes:
import github
await github.list_issues(owner="user", repo="repo")

# Virtual import resolves github to a module from make_tool_module()
# github.list_issues is a proxy() function that calls:
client.acall("tools.invoke", {"tool_call": {
    "tool_call_id": "", "tool_name": "list_issues",
    "tool_args": {"owner": "user", "repo": "repo"},
    "tool_id": "..."}
})
```

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
# CodeAct-internal tools (execute, search_tools, list_tools) are NOT available
```
