# Runtime and Run Pipeline

CommaMatrix separates declarations from runtime objects:

```text
active extension modules
  -> Python sources scan marked objects
  -> managers build descriptors and indexes
  -> lifecycle creates and reconciles instances
  -> Agent handles messages and submits runs
```

Python sources scan only modules in the current agent scope. They ignore private
names and objects whose `__module__` does not match the module being scanned.
Descriptors are declarative metadata; execution is routed back through the
source that owns the current descriptor.

## Extension Operations

`add_extensions()` imports targets and adds their module tree to one agent's
scope. `remove_extensions()` removes the scope contribution and reconciles
descriptors and instances. `reload_extensions()` replaces the imported module
tree and restores the previous usable scope if importing the replacement fails.

When the agent is already started, a successful operation refreshes active
managers and services. Removing an extension stops its owned services and
connectors but does not remove source files, dependencies, or plugin tables.

## Message Flow

The normal flow is:

```text
Agent.handle(raw)
  -> Connector.parse()
  -> on_parsed hooks
  -> split parsed items by origin
  -> submit one run per origin
  -> persist input items
  -> before_run hooks
  -> select adapter and model
  -> before_llm_call hooks
  -> LLM adapter streaming and complete blocks
  -> send and persist every complete response block
  -> before_tool_call hooks
  -> invoke tools
  -> after_tool_call hooks
  -> send and persist tool results
  -> repeat the LLM cycle when tool calls remain
  -> after_run hooks
```

`on_error` runs when the run fails. It can suppress the error; `after_run` runs
for both successful and failed runs.

Input history is persisted before the first LLM call. Complete text, reasoning,
media, and tool-call blocks are delivered before tool execution begins. Tool
results are serialized and persisted in a lock-protected sequence so branch
links remain valid when tools run concurrently.

## Context State

`RunCtx.state` lasts for one run. `RunCtx.chain_state` is copied into
`DialogItem.meta["chain"]` and restored from the branch on the next message.
Keep chain state small and serializable.

`run.tools` resolves the current tool descriptor at call time. It is available
only from contexts that contain a `RunCtx` and returns raw results without
creating ordinary dialog history.

## LLM and Streaming

The selected adapter yields complete `LLMResponseBlock` values and ends with
`StreamEnd`. If the resolved connector supports streaming, `StreamDelta` values
are sent through `send_stream_chunk()` immediately. Deltas are realtime events;
the complete blocks still pass through `Connector.send()` and storage.

Instructions are collected before each normal LLM call and inserted into the
in-memory dialog as a temporary system item. They are not persisted as normal
history.

See [core/agent/agent.py](../../../core/agent/agent.py),
[core/extensions.py](../../../core/extensions.py),
[core/classes/source.py](../../../core/classes/source.py), and
[core/agent/lifecycle.py](../../../core/agent/lifecycle.py).

