# CommaMatrix Visual Flows

## 1. Hook Invocation Flow

```mermaid
sequenceDiagram
    participant Runner as Agent Runner
    participant HM as HookManager
    participant ExtMgr as ExtensionManager
    participant Sources as ExtensionSource
    participant Handler as @Hook fn

    Runner->>HM: fire("before_llm_call", ctx)
    activate HM

    HM->>HM: lookup self._handlers["before_llm_call"]
    Note over HM: sorted by descriptor.priority (ascending)

    loop for each descriptor
        HM->>ExtMgr: _source_of(descriptor)
        ExtMgr-->>HM: ExtensionSource (owner)
        HM->>Sources: invoke(descriptor, ctx)
        activate Sources
        Sources->>Handler: fn(ctx)
        activate Handler
        Handler-->>Sources: None (or mutated ctx)
        deactivate Handler
        Sources-->>HM: done
        deactivate Sources
    end

    HM-->>Runner: done
    deactivate HM
```

---

## 2. Tool Invocation (without CodeAct)

```mermaid
sequenceDiagram
    participant Agent
    participant TM as ToolManager
    participant ExtMgr as ExtensionManager
    participant Source as ToolSource
    participant Fn as @tool fn

    Agent->>TM: call(tool_call, ctx)
    activate TM

    TM->>TM: resolve(tool_call.tool_name)
    Note over TM: 4-step chain:<br/>id → exported_name → alias → name

    alt Tool not found
        TM-->>Agent: ToolCallResult("Tool not found")
    else Tool found
        TM->>ExtMgr: _source_of(descriptor)
        ExtMgr-->>TM: ToolSource
        TM->>Source: invoke(descriptor, kwargs, ctx)

        try
            Source->>Fn: fn(**kwargs)
            activate Fn
            Fn-->>Source: result
            deactivate Fn
            Source-->>TM: result
        catch Exception as exc
            Source-->>TM: raise
            TM-->>Agent: ToolCallResult("Error: ...")
        end

        TM-->>Agent: ToolCallResult(content=result)
    end

    deactivate TM
```

---

## 3. Tool Invocation (with CodeAct)

```mermaid
sequenceDiagram
    participant LLM
    participant Agent
    participant TM as ToolManager
    participant CodeActMgr as CodeActManager
    participant Backend as SubprocessBackend
    participant Worker as CodeAct Worker
    participant RPCServer

    LLM->>Agent: execute(code, ctx)
    activate Agent

    Agent->>TM: call(tool_call, ctx)
    activate TM
    TM->>TM: resolve("execute")

    TM->>CodeActMgr: (via ToolSource invoke)
    activate CodeActMgr
    Note over CodeActMgr: retrieves from<br/>ctx.run.agent.services

    CodeActMgr->>Backend: execute(code, ctx, namespace)
    activate Backend

    Backend->>Worker: spawn python worker
    Note over Worker: isolated child process<br/>RPC over stdin/stdout

    loop tool calls inside code
        Worker->>RPCServer: RPC: tools.invoke_tool(ctx, tool_call)
        activate RPCServer
        RPCServer->>CodeActMgr: invoke_tool(ctx, tool_call)
        activate CodeActMgr
        CodeActMgr->>Agent: _run_tool_lifecycle(run, tool_call)
        activate Agent

        Agent->>TM: call(tool_call, ctx)
        TM-->>Agent: ToolCallResult

        Agent-->>CodeActMgr: (content, persist)
        deactivate Agent
        CodeActMgr-->>RPCServer: result.content
        deactivate CodeActMgr
        RPCServer-->>Worker: RPC response
        deactivate RPCServer
    end

    Worker-->>Backend: ExecutionResult
    deactivate Worker
    Backend-->>CodeActMgr: ExecutionResult
    deactivate Backend

    CodeActMgr-->>TM: formatted output (console_output())
    deactivate CodeActMgr
    TM-->>Agent: ToolCallResult
    deactivate TM
    deactivate Agent
```

---

## 4. Connector Event Listening

```mermaid
sequenceDiagram
    participant Platform as External Platform<br/>(Telegram/VK/CLI)
    participant Connector
    participant CM as ConnectorManager
    participant Agent

    Note over Connector: start() launches listener

    par Polling Connector (e.g. Telegram)
        loop polling interval
            Platform-->>Connector: GET updates
            Note over Connector: HTTP long-poll
        end
    and Webhook Connector (e.g. CLI TCP)
        Platform-->>Connector: TCP connection / POST
        Note over Connector: receives raw event
    end

    activate Connector
    Connector->>Connector: parse(raw)
    Note over Connector: Connector[OrgT] subclass<br/>converts platform-specific format

    Connector->>CM: _on_event(raw, meta)
    Note over CM: _on_event is set during<br/>_create_instance() by CM<br/>bound to Agent.handle

    CM->>Agent: handle(raw)
    activate Agent
    Agent->>Agent: ensure_started()
    Agent->>Agent: parse again, fire hooks,<br/>dispatch run loop

    deactivate Agent
    deactivate Connector
```

---

## 5. External Event via `agent.handle()`

```mermaid
sequenceDiagram
    participant Caller as External Code
    participant Agent
    participant CM as ConnectorManager
    participant HM as HookManager
    participant Runner as AgentRunner
    participant Storage
    participant LLM

    Caller->>Agent: handle(raw: dict)
    activate Agent

    Agent->>Agent: _ensure_started()

    Agent->>CM: resolve()
    CM-->>Agent: [Connector, ...]

    loop for each connector
        Agent->>Connector: parse(raw, agent)
        alt parsed successfully
            Agent->>Agent: break (use this connector)
        else returns None
            Agent->>Connector: try next
        end
    end

    alt no connector parsed
        Agent-->>Caller: return (no-op)
    end

    Agent->>Agent: _resolve_previous_item(parsed)
    Note over Agent: link to replied-to message<br/>via external_id chain

    Agent->>HM: fire(ON_PARSED, ctx)
    activate HM
    HM-->>Agent: done
    deactivate HM

    Agent->>Agent: _split_runs(parsed)
    Note over Agent: group dialog items by origin

    loop for each (run, history)
        Agent->>Runner: submit(key, run(run, history))
        activate Runner

        Runner->>Runner: cancel previous task for this key
        Runner->>Runner: spawn new asyncio.Task

        Note over Runner: cancels stale task<br/>on (origin, user) key<br/>to avoid concurrent runs
    end

    deactivate Runner
    deactivate Agent
```

---

## 6. Agent Startup (Default Settings)

```mermaid
sequenceDiagram
    participant Client
    participant Agent
    participant SM as ServiceManager
    participant TM as ToolManager
    participant HM as HookManager
    participant LM as LLMAdapterManager
    participant StM as StorageManager
    participant FStM as FileStorageManager
    participant CSM as CustomServiceManager
    participant ConM as ConnectorManager

    Client->>Agent: start()
    activate Agent

    Agent->>Agent: _ensure_started()
    activate Agent

    Agent->>Agent: add_extension("commamatrix.builtin.sqlite")
    Note over Agent: SqliteStorage becomes available

    Agent->>Agent: add_extension("commamatrix.builtin.fs")
    Note over Agent: SimpleFileStorage becomes available

    Agent->>SM: set_scope(self._extension_scope)
    activate SM
    Note over SM: propagetes scope to all 7 children<br/>sets dirty flag if changed
    SM-->>Agent: done
    deactivate SM

    Agent->>SM: start()
    activate SM
    Note over SM: TRANSACTIONAL — rollback on failure

    SM->>TM: start()
    activate TM

    TM->>TM: start sources, scan, rebuild index
    Note over TM: PythonToolSource scans scope<br/>for @tool → TOOL_ATTRIBUTE
    TM-->>SM: done
    deactivate TM

    SM->>HM: start()
    activate HM
    HM->>HM: start sources, scan, rebuild
    Note over HM: PythonHookSource scans scope<br/>for @Hook → HOOK_ATTRIBUTE
    HM-->>SM: done
    deactivate HM

    SM->>LM: start()
    activate LM
    LM->>LM: discover, create instances, start
    Note over LM: PythonProviderSource scans for<br/>LLM_ADAPTER_ATTRIBUTE
    LM-->>SM: done
    deactivate LM

    SM->>StM: start()
    activate StM
    StM->>StM: discover, create instances, start, select active
    Note over StM: scans STORAGE_ATTRIBUTE<br/>selects active_storage
    StM-->>SM: done
    deactivate StM

    SM->>FStM: start()
    activate FStM
    FStM->>FStM: discover, create, start, select active
    Note over FStM: scans FILE_STORAGE_ATTRIBUTE
    FStM-->>SM: done
    deactivate FStM

    SM->>CSM: start()
    activate CSM
    CSM->>CSM: discover custom Service subclasses
    Note over CSM: scans SERVICE_ATTRIBUTE<br/>skips provider slots
    CSM-->>SM: done
    deactivate CSM

    SM->>ConM: start()
    activate ConM
    ConM->>ConM: discover, create connectors, start listeners
    Note over ConM: scans CONNECTOR_ATTRIBUTE<br/>wires _on_event on each connector
    ConM-->>SM: done
    deactivate ConM

    SM-->>Agent: done (all children started)
    deactivate SM

    Agent->>HM: fire(ON_AGENT_START, ctx)
    activate HM
    HM-->>Agent: done
    deactivate HM

    Agent->>Agent: _started = True

    Agent->>Agent: refresh_extensions()
    Note over Agent: always runs on re-entry

    deactivate Agent
    Agent-->>Client: done
    deactivate Agent
```

---

## 7. Agent Shutdown (Default Settings)

```mermaid
sequenceDiagram
    participant Client
    participant Agent
    participant SM as ServiceManager
    participant ConM as ConnectorManager
    participant CSM as CustomServiceManager
    participant FStM as FileStorageManager
    participant StM as StorageManager
    participant LM as LLMAdapterManager
    participant HM as HookManager
    participant TM as ToolManager
    participant Runner as AgentRunner

    Client->>Agent: stop()
    activate Agent

    Agent->>Runner: stop()
    activate Runner
    Runner->>Runner: cancel all active tasks
    deactivate Runner

    Agent->>SM: stop()
    activate SM

    Note over SM,ConM: STOP IN REVERSE START ORDER

    SM->>ConM: stop()
    activate ConM
    ConM->>ConM: stop connectors (stop listeners), clear instances
    deactivate ConM

    SM->>CSM: stop()
    activate CSM
    CSM->>CSM: stop custom services
    deactivate CSM

    SM->>FStM: stop()
    activate FStM
    FStM->>FStM: stop file storage providers
    deactivate FStM

    SM->>StM: stop()
    activate StM
    StM->>StM: stop storage providers
    deactivate StM

    SM->>LM: stop()
    activate LM
    LM->>LM: stop LLM adapters
    deactivate LM

    SM->>HM: stop()
    activate HM
    HM->>HM: invalidate sources, stop
    deactivate HM

    SM->>TM: stop()
    activate TM
    TM->>TM: invalidate sources, stop
    deactivate TM

    SM->>SM: registry.clear()
    SM-->>Agent: done
    deactivate SM

    Agent->>Agent: _started = False
    deactivate Agent
    Agent-->>Client: done
```

---

## 8. `refresh()` Chain with Fingerprint Checks

### 8a. ServiceManager.refresh()

```mermaid
flowchart TD
    A["Agent ensures started /<br/>extension scope changed"] --> B["ServiceManager.refresh()"]
    B --> C{Acquire _refresh_lock}
    C --> D{_changed == True<br/>or force == True?}
    D -->|"No (clean)"| E["Return immediately<br/>(no-op)"]
    D -->|"Yes (dirty)"| F["Iterate children in order"]

    F --> G["child.refresh()"]
    G --> H{"Is child an<br/>ExtensionInstanceManager?"}

    H -->|"Yes"| I["ExtensionInstanceManager.refresh()"]
    H -->|"No"| J["Plain ExtensionManager.refresh()<br/>(subclasses)"]

    J --> K["ExtensionManager.scan()"]
    K --> L["ExtensionManager.refresh()"]
    L --> M["done"]

    I --> N["ExtensionManager.refresh()<br/>→ scan()"]
    N --> O["ExtensionInstanceManager.<br/>_reconcile_instances()"]
    O --> P["ExtensionInstanceManager.<br/>_refresh_instances()"]
    P --> M

    M --> Q["More children?"]
    Q -->|"Yes"| R["next child → G"]
    Q -->|"No"| S["_changed = False"]
    S --> T["done"]
```

### 8b. ExtensionManager.scan() — Fingerprint Check Detail

```mermaid
flowchart TD
    A["scan()"] --> B["For each mounted source:"]
    B --> C{"source.available?"}
    C -->|"No"| D["track empty descriptor set"]
    C -->|"Yes"| E["source.scan() → list[D]"]
    E --> F{"descriptor.id<br/>duplicate across sources?"}
    F -->|"Yes"| G["raise ValueError"]
    F -->|"No"| H["collect into descriptors dict"]
    H --> D
    D --> I["_calculate_fingerprint(descriptors)"]
    I --> J{"fingerprint ==<br/>self._fingerprint?"}

    J -->|"Yes (no change)"| K["update _source_descriptor_ids"]
    K --> L["return False<br/>(skip rebuild)"]

    J -->|"No (changed)"| M["self._descriptors = descriptors"]
    M --> N["self._fingerprint = fingerprint"]
    N --> O["_rebuild()"]
    O --> P{"Which subclass?"}

    P -->|"HookManager"| Q["group by event,<br/>sort by priority"]
    P -->|"ToolManager"| R["build _by_alias, _by_name,<br/>_by_exported_name index maps"]
    P -->|"ExtensionInstanceManager"| S["no extra rebuild<br/>(reconciliation handles it)"]

    Q --> T
    R --> T
    S --> T

    T --> U["_notify_change()"]
    U --> V["on_change() callback"]
    V --> W["ServiceManager._mark_changed()"]
    W --> X["return True<br/>(changes applied)"]
```

### 8c. ExtensionInstanceManager._reconcile_instances() — Instance Lifecycle

```mermaid
flowchart TD
    A["_reconcile_instances()"] --> B["desired = {d.id: d<br/>for d in descriptors}"]
    B --> C["**CASE 1: Removed**"]

    C --> D{"sid in _instances<br/>but NOT in desired?"}
    D -->|"Yes"| E["pop instance"]
    E --> F["_stop_instance(instance)"]
    F --> G["_on_instance_removed(instance)"]
    G --> D
    D -->|"No (done)"| H["**CASE 2: Changed**"]

    H --> I{"sid in desired AND<br/>old_fp != new_fp?"}
    I -->|"Yes"| J["pop instance"]
    J --> K["_stop_instance(instance)"]
    K --> L["_on_instance_removed(instance)"]
    L --> I
    I -->|"No (done)"| M["**CASE 3: New**"]

    M --> N{"sid in desired<br/>but NOT in _instances?"}
    N -->|"Yes"| O["_create_instance(descriptor)"]
    O --> P["_start_instance(instance)"]
    P --> Q["store in _instances<br/>record fingerprint<br/>append to _start_order"]
    Q --> R["_on_instance_added(instance, sid, descriptor)"]
    R --> N
    N -->|"No (done)"| S["_refresh_instances()"]
    S --> T["asyncio.gather<br/>_refresh_instance(inst)<br/>for all running instances"]
    T --> U["done"]
```
