# Hooks

Hooks are top-level functions that observe or modify an agent lifecycle event.
They may be synchronous or asynchronous. Use an async hook for I/O.

## Events

| Decorator           | Context             | Main use                                        |
|---------------------|---------------------|-------------------------------------------------|
| `@on_agent_start`   | `OnAgentStartCtx`   | Initialization after lifecycle startup          |
| `@on_parsed`        | `OnParsedCtx`       | Inspect or modify parsed input                  |
| `@before_run`       | `BeforeRunCtx`      | Abort or prepare a run                          |
| `@before_llm_call`  | `BeforeLlmCallCtx`  | Change dialog, tools, model, or call parameters |
| `@after_llm_call`   | `AfterLlmCallCtx`   | Inspect or modify the complete response         |
| `@before_tool_call` | `BeforeToolCallCtx` | Authorize, modify, or abort a tool call         |
| `@after_tool_call`  | `AfterToolCallCtx`  | Inspect or modify the tool result               |
| `@before_send`      | `BeforeSendCtx`     | Modify an item before delivery and persistence  |
| `@after_send`       | `AfterSendCtx`      | Observe completed delivery and persistence      |
| `@on_error`         | `OnErrorCtx`        | Observe or suppress run errors                  |
| `@after_run`        | `AfterRunCtx`       | Cleanup after success or failure                |

The complete event order and persistence boundaries are described in
[runtime.md](runtime.md).

## Run Context

`RunCtx.state` is temporary state for one run. `RunCtx.chain_state` is intended
for state that must survive across messages in a conversation chain. The latter
is serialized into `DialogItem.meta["chain"]`.

```python
from commamatrix import BeforeRunCtx, before_run


@before_run
async def mark_run(ctx: BeforeRunCtx) -> None:
    ctx.run.state["prepared"] = True
    ctx.run.chain_state["workflow"] = "default"
```

Contexts that contain a `run` can use `ctx.run.tools`. `OnAgentStartCtx` and
`OnParsedCtx` do not contain a `RunCtx`, so they cannot use that facade.

## Mutations

`BeforeRunCtx.abort = True` skips the run. `BeforeLlmCallCtx` exposes the current
dialog and tools and can change the selected adapter/model, reasoning mode, API
settings, or LLM call parameters. `BeforeToolCallCtx.abort_tool_call = True`
skips a tool call; `abort_reason` becomes its result message.

```python
from commamatrix import BeforeToolCallCtx, before_tool_call


@before_tool_call
async def guard_external_delete(ctx: BeforeToolCallCtx) -> None:
    if ctx.tool_call.tool_name == "project_delete" and not ctx.run.state.get(
        "approved"
    ):
        ctx.abort_tool_call = True
        ctx.abort_reason = "Explicit approval is required."
```

`BeforeToolCallCtx.follow_up_items` can add input items after the tool result.
Use this only when the tool deliberately produces additional dialog input.

## Ordering

Hooks in one event are ordered by `before` and `after` constraints first. Among
ready unconstrained hooks, higher `priority` runs earlier and equal priorities
retain declaration order.

```python
from commamatrix import BeforeLlmCallCtx, before_llm_call


@before_llm_call(priority=20)
async def load_preferences(ctx: BeforeLlmCallCtx) -> None:
    ctx.run.state["preferences_loaded"] = True


@before_llm_call(after=load_preferences)
async def apply_preferences(ctx: BeforeLlmCallCtx) -> None:
    if ctx.run.state.get("preferences_loaded"):
        ctx.llm_call_params["temperature"] = 0.4
```

Unknown constraint names are ignored. Cycles raise `CyclicConstraintError` and
prevent the manager from rebuilding successfully. Prefer callable references
when the constrained functions are in the same module.

## Errors and Cleanup

An `on_error` hook can set `ctx.suppress = True` to prevent the error from being
re-raised. `after_run` still runs and receives the error in `ctx.error`.

```python
from commamatrix import OnErrorCtx, on_error


@on_error
async def suppress_expected_timeout(ctx: OnErrorCtx) -> None:
    if isinstance(ctx.error, TimeoutError):
        ctx.suppress = True
```

See [components/hook.py](../../../components/hook.py) and
[core/classes/ordering.py](../../../core/classes/ordering.py).

