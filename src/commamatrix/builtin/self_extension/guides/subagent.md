# Headless Subagents

The optional subagent built-in runs an agent without a user-facing connector
and returns its generated response to the code that submitted it. It provides:

- the `Agent.submit_run()` API for application and extension code;
- the `subagent_call_subagent` tool for model-driven delegation;
- an internal connector that captures output and transports completion back to
  the submitter.

A headless run is still a normal CommaMatrix run with an LLM call, tools,
hooks, history, and cleanup. "Headless" describes its transport, not a
separate process or a security sandbox.

## Activate the Built-in

Install and activate the built-in on agents that expose the delegation tool:

```python
await interface.add_extensions("commamatrix.builtin.subagent")
```

The target agent's internal subagent transport is activated lazily by
`Agent.submit_run()`. Explicit activation is also fine:

```python
await executor.add_extensions("commamatrix.builtin.subagent")
```

The subagent extension does not provide an LLM adapter, a model, storage, or
application tools. Each target agent must activate and configure those pieces
independently. Extension scopes are per-agent, so an executor can have file,
web, or CodeAct capabilities without exposing those capabilities on the
interface agent.

## Agent Registry

Every `Agent` registers itself under its current `name`. The model-facing tool
resolves the `subagent` argument through this process-local registry:

```python
from commamatrix import Agent


interface = Agent("interface")
executor = Agent(
    "executor",
    description="Performs delegated research and tool-based work.",
)
```

Names should be unique and stable. The built-in `available_subagents`
instruction lists registered names and descriptions for normal runs. It is not
added to a headless run because the normal instruction aggregator is skipped
for headless execution.

## Model-Driven Delegation

The built-in registers `call_subagent` with `alias="subagent"`. Its public tool
name is therefore `subagent_call_subagent`:

```text
subagent_call_subagent(
    subagent="executor",
    instructions="Inspect the repository and summarize the relevant findings.",
    tools="^(?!subagent_).*$",
    continue_from_here=false,
    wait_for_result=true,
)
```

The tool parameters are:

| Parameter            | Meaning                                                                                                           |
|----------------------|-------------------------------------------------------------------------------------------------------------------|
| `subagent`           | Exact registered agent name. The before-tool hook defaults a missing value to the current agent.                  |
| `instructions`       | Optional system-role input for the new run. It is not an automatic copy of the caller's instructions.             |
| `tools`              | Tool allowlist: `all`, `None`/empty for no ordinary tools, or a regex matched with `re.fullmatch`.                |
| `continue_from_here` | Continue the current dialog branch instead of starting a fresh branch.                                            |
| `parent_item_id`     | Internal continuation value. The before-tool hook replaces it with the current tool call's persisted parent item. |
| `wait_for_result`    | Wait for the run and return its response, or start it in the background.                                          |

When `wait_for_result=True`, the tool returns the captured output blocks joined
by blank lines. If the run is aborted before producing a result, it returns
`Subagent run was aborted`. With `False`, it returns immediately and the
background run continues independently.

The model-facing tool is useful for an interface/executor split:

```python
await interface.add_extensions(
    "commamatrix.builtin.subagent",
    "my_project.interface_rules",
)
await executor.add_extensions(
    "commamatrix.builtin.llm_http_adapter",
    "my_project.executor_tools",
)
```

The interface should include the complete user request and relevant context in
`instructions` when delegating to a different agent. Do not assume that the
executor automatically sees the interface agent's system instructions,
conversation, or tools.

## Programmatic Runs

Use `Agent.submit_run()` when delegation is initiated by application or
extension code rather than by an LLM tool call:

```python
result = await executor.submit_run(
    instructions="Produce a concise inventory of the project files.",
    tools="",
    wait_for_result=True,
)

if result is not None:
    print(result.final_answer or "")
```

`tools` is a required keyword argument. Use `tools="all"` to allow every
ordinary tool, a regular expression to select public tool names, or `tools=""`
to allow none. A regex is applied with a full match, so `reports_.*` matches
`reports_build` but not `project_reports_build`.

The lower-level function is also available as
`commamatrix.builtin.subagent.submit_run(agent, ...)`. The agent method returns
`AfterLlmCallCtx | str | None`:

- With `wait_for_result=True`, it returns `AfterLlmCallCtx`, or `None` when the
  runner skips or aborts the run.
- With `wait_for_result=False`, it returns `"OK"` after submission or
  `"Subagent run was skipped"` when the runner conflict policy skips it.
- `on_error` can receive failures from a background run when using the direct
  API.

A run must provide at least one of these inputs:

- a non-empty `instructions` string;
- a list of `dialog_items`;
- a `parent_item_id` from which to load an existing branch.

`instructions` is stored as a `SYSTEM` input item for the headless run. It is
different from `@instruction` output: normal dynamic instruction aggregation is
skipped for headless runs, while the explicit input is part of the submitted
history.

## Dialog Continuation

By default, a headless run starts a fresh branch. To continue a branch from
application code, pass a persisted `parent_item_id`:

```python
await agent.submit_run(
    parent_item_id=last_item_id,
    instructions="Continue the analysis from this point.",
    tools="analysis_.*",
    wait_for_result=True,
)
```

For `subagent_call_subagent`, set `continue_from_here=True`. The
`prepare_subagent_call` hook obtains the persisted item immediately before the
current tool call and writes that value into `parent_item_id`; a value supplied
by the model is not trusted. If the current tool call has no persisted parent,
the call fails instead of silently starting an unrelated branch.

Continuation is meaningful only when the target agent can resolve the item in
its own storage. For a different agent with separate storage, pass the relevant
context explicitly through `instructions` or `dialog_items` instead of
reusing the caller's item ID.

The target's branch is persisted with an internal origin and is not sent to an
external connector. The captured `OUTPUT` items are returned to the submitter;
other target history remains target-agent history.

## Tool Policy

The `tools` value is written into the headless run's chain state and enforced
both when the model receives its tool list and when a tool call is executed.
This prevents a model from bypassing the visible allowlist by emitting a tool
name directly.

Tools marked with `codeact=False` are intentionally retained as CodeAct control
tools and are not removed by this policy. Treat `tools` as an allowlist for
ordinary application tools, not as a complete authorization boundary. Apply
separate authorization, confirmation, and tenant checks before exposing a
delegation tool to untrusted users.

The `subagent_call_subagent` tool itself is included when the allowlist matches
its public name. `tools="all"` therefore permits nested delegation and can
create unbounded delegation chains; use a negative-match policy such as
`^(?!subagent_).*$` when the executor should not delegate further.

## Concurrency and Cleanup

Headless runs use `AgentRunner` keys. The default key is based on
`runner_namespace`, `user`, and `parent_item_id`; the default namespace is
`subagent`, and the tool submits with `user="agent"`. The default
`conflict_policy="skip"` prevents a second active run with the same key from
starting. Use the direct API's `runner_key` to distinguish independent jobs,
or `conflict_policy="replace"` when a new job should cancel the old one.

`wait_for_result=False` returns before the LLM run completes. Handle failures
with `on_error` when using the direct API, and ensure the target agent remains
running for the duration of the background work. Stopping the target agent
cancels active runs and completes pending internal waiters with an error.

The internal connector is lifecycle-owned. Do not create or close an
`InternalConnector` manually. Use `Agent.stop()` or the agent async context
manager so pending runs, connector state, and runner tasks are cleaned up.

## Security and Boundaries

Subagents run in the same Python process and normally share the host's
credentials, filesystem permissions, and installed dependencies. A separate
`Agent` is an isolation boundary for configuration and extension scope, not a
security sandbox. If the target activates CodeAct, its generated code has the
trust model described in [codeact.md](codeact.md).

Before exposing delegation, validate the caller's authorization, select a
target allowlist, restrict tools, prevent unintended nested delegation, and
protect side-effecting tools with their own checks. Keep secrets out of
instructions and dialog content.

See [builtin/subagent/tools.py](../../subagent/tools.py),
[builtin/subagent/submit.py](../../subagent/submit.py),
[builtin/subagent/hooks.py](../../subagent/hooks.py),
[builtin/subagent/connector.py](../../subagent/connector.py),
[runtime.md](runtime.md), and [dialog.md](dialog.md).
