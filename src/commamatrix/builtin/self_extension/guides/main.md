# CommaMatrix Extension Guide

This is the starting point for writing an extension or a third-party integration.
It is intentionally short: use the detailed guides when the extension needs an
exact API contract, context field, or lifecycle rule.

The guides are also available through `self_extension.read_guide`. Read this
file first, then request only the detailed sections needed for the current task.

## Mental Model

An extension is an importable Python module that contributes declarations to one
agent's extension scope. The runtime then:

1. Imports the module and its imported submodules.
2. Scans the active scope for marked functions and classes.
3. Builds descriptors through sources and reconciles them through managers.
4. Starts, refreshes, and stops the resulting services in lifecycle order.

The scope belongs to one `Agent`; activating a module does not activate it for
other agents in the same process.

## Choose an Extension Point

| Need                                           | Use                          |
|------------------------------------------------|------------------------------|
| Add an action the model can call               | `@tool`                      |
| Add reusable or dynamic system-prompt text     | `@instruction`               |
| React to or change a lifecycle event           | A hook such as `@before_run` |
| Own a long-lived client or background resource | `Service`                    |
| Add some form of input / output                | `Connector`                  |
| Persist extension-owned structured data        | `BaseTable`                  |
| Provide data persistence                       | `Storage`                    |
| Provide file persistence                       | `FileStorage`                |
| Provide models and LLM protocol handling       | `LLMAdapter`                 |
| Add ordered per-agent runtime component        | `@lifecycle_component`       |

Choose the smallest extension point that solves the problem. A tool does not
need a service, configuration layer, connector, or lifecycle component unless it
actually needs those capabilities.

## Minimal Extension

Use explicit imports in extension code. The package root re-exports the public
component API, but optional built-ins such as MCP, CodeAct, and the planner are
activated and imported separately.

```python
# my_project/status.py
from commamatrix import tool


@tool(alias="project")
async def current_status() -> str:
    """Return the current project status."""
    return "OK"
```

Activate an importable extension for the current agent:

```python
await agent.add_extensions("my_project.status")
```

For a reusable response rule, use an instruction instead:

```python
from commamatrix import InstructionCtx, instruction


@instruction
def concise_answers(_ctx: InstructionCtx) -> str:
    return "Prefer direct answers with only the detail needed for the task."
```

## Where Code Lives

Self-written extensions normally belong in the host project's
`.commamatrix/plugins` directory. The directory is created when an agent starts
with `auto_load_plugins=True`, which is the default.

```text
<CWD>/
    .commamatrix/
        plugins/
            response_style.py
            weather/
                __init__.py
                tools.py
```

At startup, the runtime discovers direct `.py` files and direct package
directories. A package's nested modules must be imported by its `__init__.py`:

```python
from . import tools
```

Creating a nested file alone does not make it discoverable. Declarations must
be top-level objects in their defining module. Private names and cross-module
re-exports are not registered by the Python source scanner.

Use `auto_load_plugins=False` when the host must activate workspace extensions
explicitly. Use `add_extensions()`, `remove_extensions()`, and
`reload_extensions()` for import names, module objects, or Python paths. A
module created while an already-running agent is active must be added explicitly
before that agent can use it.

Extension paths are resolved to their canonical import names; the runtime does
not create synthetic module names. Keep the import path unambiguous and use the
same target form for later reloads.

## Import Rules

Importing an extension should declare objects, not start the application. Do
not make network calls, open files, create long-lived clients, or start tasks at
module import time. Allocate resources in `start()` and release owned resources
in `stop()`.

Use `async def` for tools and hooks that perform I/O. A synchronous tool runs
directly on the event loop; blocking synchronous work can stall every run of the
agent.

Keep credentials in `ConfigField` values, host configuration, or environment
variables. Do not put secrets in source code, tool descriptions, metadata, or
dialog content.

## Lifecycle Summary

`Service` is the normal discoverable extension service. `AbstractService` is the
bare lifecycle contract and is normally used directly only for a lifecycle
component. Provider classes and `Connector` have their own discovery markers and
managers; they are not ordinary `Service` subclasses.

- `start()` allocates resources when the extension becomes active.
- `refresh()` reconciles active state after scope changes and may run often.
- `stop()` releases resources when the extension is removed or the agent stops.

Startup is transactional: if a lifecycle child fails, already-started children
are rolled back. Removal and reload reconcile descriptors and running instances
instead of leaving the old extension active.

## Runtime Rules

At a high level, a message goes through connector parsing, parsing hooks, input
history persistence, run hooks, an LLM call, complete response delivery, tool
execution, and another LLM iteration when tools were called. Complete response
blocks are delivered and persisted before their tool calls execute.

Instructions are collected before each LLM call and inserted as a temporary
system item. They are not ordinary persisted conversation history. A run's
`state` is temporary; `chain_state` is carried across messages through dialog
metadata.

When filesystem tools are active, a non-empty `<CWD>/agents.md` is loaded as a
separate system item immediately after the generated system instructions.

Read `runtime.md` before changing run behavior, persistence, streaming, or hook
placement.

## Safety Rules

- Validate authorization, input, rate limits, and confirmation requirements before external side effects.
- Set `http_host` to `127.0.0.1` for local HTTP development unless public exposure is intentional and protected.
- Reuse `agent.http_client` for ordinary extension HTTP work; close separately-owned clients yourself.
- Keep filesystem access within the configured path policy.
- Treat CodeAct subprocess execution as arbitrary Python execution, not a security sandbox.
- Preserve URL validation and redirect checks in web-facing tools.
- Stop listeners, clients, and background tasks when an extension is removed or reloaded.

## Detailed Guides

- [Runtime](runtime.md)
- [Tools](tools.md)
- [Hooks](hooks.md)
- [Instructions](instructions.md)
- [Configuration](configuration.md)
- [Services](services.md)
- [Lifecycle components](lifecycle.md)
- [Connectors](connectors.md)
- [Dialog and origins](dialog.md)
- [Plugin tables](tables.md)
- [Storage and LLM providers](providers.md)
- [Scheduled tasks](planner.md)
- [MCP](mcp.md)
- [HTTP server](http.md)
- [CodeAct](codeact.md)
- [Security](security.md)

## Checklist

1. Choose the smallest extension point.
2. Put declarations in importable top-level modules.
3. Import every contribution module from a package initializer.
4. Keep import-time code free of resource allocation and side effects.
5. Define configuration only when the extension needs it.
6. Use async code for external I/O and the shared HTTP client where appropriate.
7. Activate or reload the extension in the current agent and verify its cleanup path.

