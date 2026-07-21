# CommaMatrix Visual Flows

## 1. Hook Invocation Flow

```mermaid
sequenceDiagram
    participant Runner as AgentRunner
    participant HM as HookManager
    participant ExtMgr as Manager
    participant Sources as Source
    participant Handler as @Hook fn

    Runner->>HM: fire("before_llm_call", ctx)
    activate HM

    HM->>HM: lookup self._handlers["before_llm_call"]
    Note over HM: sorted by descriptor.priority (descending)

    loop for each descriptor
        HM->>ExtMgr: _source_of(descriptor)
        ExtMgr-->>HM: Source (owner)
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
    participant ExtMgr as Manager
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

        alt Success
            Source->>Fn: fn(**kwargs)
            activate Fn
            Fn-->>Source: result
            deactivate Fn
            Source-->>TM: result
        else Exception
            Source-->>TM: exception propagates
            Note over TM: caught in call()<br/>wraps in ToolCallResult
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
    participant CodeActMgr as CodeActService
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
        Worker->>+RPCServer: RPC: tools.invoke_tool(ctx, tool_call)
        RPCServer->>+CodeActMgr: invoke_tool(ctx, tool_call)
        CodeActMgr->>+Agent: _run_tool_lifecycle(run, tool_call)
        Agent->>TM: call(tool_call, ctx)
        TM-->>Agent: ToolCallResult
        Agent-->>-CodeActMgr: (content, persist)
        CodeActMgr-->>-RPCServer: result.content
        RPCServer-->>-Worker: RPC response
    end

    Worker-->>Backend: ExecutionResult
    Note over Worker: process exits

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
    Note over Connector: Connector subclass<br/>converts platform-specific format

    Connector->>Agent: self.agent.handle(raw)
    Note over Connector: calls self.agent.handle directly
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
    participant SM as AgentLifecycle
    participant TM as ToolManager
    participant HM as HookManager
    participant IM as InstructionManager
    participant LM as LLMAdapterManager
    participant StM as StorageManager
    participant FStM as FileStorageManager
    participant SMgr as ServiceInstanceManager
    participant ConM as ConnectorManager

    Client->>Agent: start()
    activate Agent

    Agent->>Agent: _ensure_started()
    activate Agent

    alt auto_load_main (default True)
        Agent->>Agent: add_extensions("__main__")
    end

    alt no Storage in scope
        Agent->>Agent: add_extensions("commamatrix.builtin.sqlite")
        Note over Agent: SqliteStorage becomes available
    end

    alt no FileStorage in scope
        Agent->>Agent: add_extensions("commamatrix.builtin.fs")
        Note over Agent: SimpleFileStorage becomes available
    end

    Agent->>SM: set_scope(self._extension_scope)
    activate SM
    Note over SM: propagates scope to all 8 children<br/>sets "changed" flag if changed
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

    SM->>IM: start()
    activate IM
    IM->>IM: start sources, scan, rebuild
    Note over IM: PythonInstructionSource scans scope<br/>for @instruction → INSTRUCTION_ATTRIBUTE
    IM-->>SM: done
    deactivate IM

    SM->>LM: start()
    activate LM
    LM->>LM: discover, create instances, start
    Note over LM: PythonServiceSource scans for<br/>LLM_ADAPTER_ATTRIBUTE
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

    SM->>SMgr: start()
    activate SMgr
    SMgr->>SMgr: discover Service subclasses
    Note over SMgr: scans SERVICE_ATTRIBUTE<br/>generic discovery for custom services
    SMgr-->>SM: done
    deactivate SMgr

    SM->>ConM: start()
    activate ConM
    ConM->>ConM: discover, create connectors, start listeners
    Note over ConM: scans CONNECTOR_ATTRIBUTE<br/>uses self.agent.handle
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
    participant SM as AgentLifecycle
    participant ConM as ConnectorManager
    participant SMgr as ServiceInstanceManager
    participant FStM as FileStorageManager
    participant StM as StorageManager
    participant LM as LLMAdapterManager
    participant HM as HookManager
    participant IM as InstructionManager
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

    SM->>SMgr: stop()
    activate SMgr
    SMgr->>SMgr: stop custom services
    deactivate SMgr

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

    SM->>IM: stop()
    activate IM
    IM->>IM: invalidate sources, stop
    deactivate IM

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

### 8a. AgentLifecycle.refresh()

```mermaid
flowchart TD
    A["Agent ensures started /<br/>extension scope changed"] --> B["AgentLifecycle.refresh()"]
    B --> C{Acquire _refresh_lock}
    C --> D{_changed == True<br/>or force == True?}
    D -->|"No (clean)"| E["Return immediately<br/>(no-op)"]
    D -->|"Yes (changed)"| F["Iterate children in order"]

    F --> G["child.refresh()"]
    G --> H{"Is child an<br/>InstanceManager?"}

    H -->|"Yes"| I["InstanceManager.refresh()"]
    H -->|"No"| J["Plain Manager.refresh()<br/>(subclasses)"]

    J --> K["Manager.scan()"]
    K --> L["Manager.refresh()"]
    L --> M["done"]

    I --> N["Manager.refresh()<br/>→ scan()"]
    N --> O["InstanceManager.<br/>_reconcile_instances()"]
    O --> P["InstanceManager.<br/>_refresh_instances()"]
    
    P --> M --> Q["More children?"]
    Q -->|"Yes"| R["next child"] --> G
    Q -->|"No"| S["_changed = False"] --> T["done"]
```

### 8b. Manager.scan() — Fingerprint Check Detail

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
    P -->|"InstructionManager"| InsOrd["sort by priority<br/>with before/after constraints"]
    P -->|"ToolManager"| R["build _by_alias, _by_name,<br/>_by_exported_name index maps"]
    P -->|"InstanceManager"| S["no extra rebuild<br/>(reconciliation handles it)"]

    Q --> T
    InsOrd --> T
    R --> T
    S --> T

    T --> U["_notify_change()"]
    U --> V["on_change() callback"]
    V --> W["AgentLifecycle._mark_changed()"]
    W --> X["return True<br/>(changes applied)"]
```

### 8c. InstanceManager._reconcile_instances() — Instance AgentLifecycle

```mermaid
flowchart TD
    A["_reconcile_instances()"] --> B["desired = {d.id: d<br/>for d in descriptors}"]
    B --> C["CASE 1: Removed"]

    C --> D{"sid in _instances<br/>but NOT in desired?"}
    D -->|"Yes"| E["pop instance"]
    E --> F["_stop_instance(instance)"]
    F --> G["_on_instance_removed(instance)"]
    G --> D
    D -->|"No (done)"| H["CASE 2: Changed"]

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

---

## 9. Manager & Service Inheritance

### Part A — AbstractService → Manager Hierarchy

```mermaid
classDiagram
    class AbstractService {
        «ABC»
        + agent: Agent
        + __init__(agent: Agent)
        + start() async … initialize resources
        + stop() async … release resources
        + refresh() async … sync with extensions
    }

    class Service {
        «ABC»
        + __init_subclass__() → stamps SERVICE_ATTRIBUTE
        ──────────────────────────────────
        Inherits: start, stop, refresh
        Adds: auto-discovery via SERVICE_ATTRIBUTE
    }
    AbstractService <|-- Service : extends

    class Storage {
        + __init_subclass__() → stamps STORAGE_ATTRIBUTE
        + save_event(entry) async → int | None
        + get_branch(last_item_id) async → list[DialogItem]
        + find_item_id_by_external_id(eid, origin) async → int | None
    }
    AbstractService <|-- Storage : extends (no SERVICE_ATTRIBUTE)

    class FileStorage {
        + __init_subclass__() → stamps FILE_STORAGE_ATTRIBUTE
        + save(data, ext) async → str
        + get(file_id) async → bytes | None
        + delete(file_id) async → bool
    }
    AbstractService <|-- FileStorage : extends (no SERVICE_ATTRIBUTE)

    class LLMAdapter {
        + __init_subclass__() → stamps LLM_ADAPTER_ATTRIBUTE
        + ask_llm(ctx) async → LLMResponse
    }
    AbstractService <|-- LLMAdapter : extends (no SERVICE_ATTRIBUTE)

    class Connector {
        + origin_types: ClassVar[tuple[type[DialogOrigin], ...]]
        + __init_subclass__() → stamps CONNECTOR_ATTRIBUTE
        + start() async … launches listener
        + stop() async … cancels listener
        + parse(raw, agent) async → OnParsedCtx | None
        + send(origin, item) async → str
        + typing(origin) → AsyncIterator
        + listen(on_event) async … platform loop
    }
    AbstractService <|-- Connector : extends (no SERVICE_ATTRIBUTE)

    class Manager~D~ {
        «Generic[D: Descriptor]»
        # _sources: list[Source[D]]
        # _descriptors: dict[str, D]
        # _fingerprint: str | None
        + on_change: Callable | None
        + start() async → refresh at end
        + stop() async → invalidate sources
        + refresh() async → scan()
        + mount(source)
        + unmount(source)
        + scan() → bool … fingerprint-based
        + invalidate(source) → bool
    }
    AbstractService <|-- Manager : extends

    class ToolManager {
        + call(tool_call, ctx) async → ToolCallResult
        + resolve(name) → ToolDescriptor
        + schemas() → list[dict]
        + invoke(tool_call) async → Any
        ──────────────────────────────────
        Inherits: mount, scan, invalidate, fingerprint check
        Adds: alias/name/exported_name index maps
    }
    Manager <|-- ToolManager : extends

    class HookManager {
        - _handlers: dict[str, list[HookDescriptor]]
        + fire(event, ctx) async … priority order
        ──────────────────────────────────
        Inherits: mount, scan, invalidate
        Adds: event-grouped, priority-sorted handler map
    }
    Manager <|-- HookManager : extends

    class InstructionManager {
        - _ordered: list[InstructionDescriptor]
        + collect(run) async → list[str]
        + set_scope(scope)
        ──────────────────────────────────
        Inherits: mount, scan, invalidate
        Adds: ordered instruction collection with before/after constraints
    }
    Manager <|-- InstructionManager : extends

    class InstanceManager~D,I~ {
        «Generic — I: AbstractService»
        # _instances: dict[str, I]
        # _start_order: list[str]
        + instances → list[I]
        # _create_instance(descriptor) → I
        # _start_instance(instance) async
        # _stop_instance(instance) async
        # _refresh_instance(instance) async
        # _on_instance_added(instance, sid, descriptor)
        # _on_instance_removed(instance)
        # _reconcile_instances()
        # _refresh_instances() async
        ──────────────────────────────────
        Inherits: mount, scan, fingerprint, invalidate
        Adds: instance create/start/stop/reconcile lifecycle
    }
    Manager <|-- InstanceManager : extends

    class ServiceInstanceManager {
        # base_type: type[AbstractService]
        # marker_attribute: str
        # id_prefix: str
        ──────────────────────────────────
        Inherits: instance lifecycle
        Adds: creates via service_cls(agent), registry hooks, class-var source defaults
    }
    InstanceManager <|-- ServiceInstanceManager : D=ServiceDescriptor, I=AbstractService

    class ActiveServiceInstanceManager {
        «abstract — subclass must set base_type, marker_attribute, active_field»
        # base_type: type[AbstractService]
        # marker_attribute: str
        # id_prefix: str
        # active_field: ConfigField[str | None]
        - _active_id: str | None
        + _active → instance (property)
        # _select_active() … picks configured or first
        ──────────────────────────────────
        Inherits: instance lifecycle + registry hooks
        Adds: active-instance selection by config or “first”
    }
    ServiceInstanceManager <|-- ActiveServiceInstanceManager : extends

    class StorageManager {
        ──────────────────────────────────
        Inherits: active selection
        Adds: delegates save_event/get_branch/find → active Storage
    }
    ActiveServiceInstanceManager <|-- StorageManager : base_type=Storage, marker_attribute=STORAGE_ATTRIBUTE

    class FileStorageManager {
        ──────────────────────────────────
        Inherits: active selection
        Adds: delegates save/get/delete → active FileStorage
    }
    ActiveServiceInstanceManager <|-- FileStorageManager : base_type=FileStorage, marker_attribute=FILE_STORAGE_ATTRIBUTE

    class LLMAdapterManager {
        ──────────────────────────────────
        Inherits: instance lifecycle (NOT active selection)
        Adds: first-adapter pattern — forwards ask_llm → first instance
    }
    ServiceInstanceManager <|-- LLMAdapterManager : extends (skips active selection)

    class ConnectorManager {
        + resolve() → list[Connector]
        ──────────────────────────────────
        Inherits: instance lifecycle
        Adds: wires self.agent.handle
    }
    ServiceInstanceManager <|-- ConnectorManager : extends (scans CONNECTOR_ATTRIBUTE)

    class AgentLifecycle {
        «root composite — NOT an AbstractService»
        - _children: list[Manager]
        - _changed: bool
        - _registry: ServiceInstanceRegistry
        + registry → ServiceInstanceRegistry
        + get_manager(cls) → Manager | None
        + start() async … transactional, rollback on fail
        + stop() async … reverse order
        + refresh(force) async … no-op when clean
        + set_scope(scope) … propagates to all children
    }

    AgentLifecycle o--> ToolManager : owns
    AgentLifecycle o--> HookManager : owns
    AgentLifecycle o--> InstructionManager : owns
    AgentLifecycle o--> LLMAdapterManager : owns
    AgentLifecycle o--> StorageManager : owns
    AgentLifecycle o--> FileStorageManager : owns
    AgentLifecycle o--> ServiceInstanceManager : owns (generic, custom Service discovery)
    AgentLifecycle o--> ConnectorManager : owns

    class ServiceInstanceRegistry {
        + get(key: type[T]) → T | None
        + require(key: type[T]) → T
        + get_by_id(descriptor_id) → object | None
        + get_all(base: type[T]) → list[T]
        + remove_by_instance(instance)
        + clear()
    }
    AgentLifecycle *--> ServiceInstanceRegistry : creates & owns
    ServiceInstanceManager --> ServiceInstanceRegistry : registers instances
```

**What each level inherits:**

| Level | Inherits from | Key inherited capabilities |
|-------|--------------|---------------------------|
| `Service` | `AbstractService` | `start()` / `stop()` / `refresh()` lifecycle + stamps `SERVICE_ATTRIBUTE` |
| `Storage`, `FileStorage`, `LLMAdapter` | `AbstractService` | `start()` / `stop()` / `refresh()` + stamps own provider marker |
| `Connector` | `AbstractService` | `start()` (launches listener) / `stop()` (cancels) + stamps `CONNECTOR_ATTRIBUTE` |
| `Manager[D]` | `AbstractService` | source mounting, fingerprint-based `scan()`, invalidation, `start()`→refresh (core/base/manager.py) |
| `ToolManager` | `Manager` | name-resolution index maps, `call()` / `resolve()` / `schemas()` |
| `HookManager` | `Manager` | event-grouped handler map, priority-ordered `fire()` |
| `InstructionManager` | `Manager` | ordered instruction collection, `collect()` → system prompt fragments |
| `InstanceManager[D,I]` | `Manager` | instance create/start/stop/reconcile lifecycle + refresh |
| `ServiceInstanceManager` | `InstanceManager` | *Binds D=ServiceDescriptor I=AbstractService*; integrates with `ServiceInstanceRegistry` |
| `ActiveServiceInstanceManager` | `ServiceInstanceManager` | active-instance selection (`_select_active()`) by config or first-available |
| `StorageManager` | `ActiveServiceInstanceManager` | delegates to active `Storage` |
| `FileStorageManager` | `ActiveServiceInstanceManager` | delegates to active `FileStorage` |
| `LLMAdapterManager` | `ServiceInstanceManager` | first-adapter pattern (no active selection) |
| `ServiceInstanceManager` (generic) | `ServiceInstanceManager` | discovers custom `Service` subclasses (default params) |
| `ConnectorManager` | `ServiceInstanceManager` | wires `agent.handle`, `resolve()` returns connectors |

---

### Part B — Source & Descriptor Hierarchy

```mermaid
classDiagram
    class Source~D~ {
        «ABC — Generic[D: Descriptor]»
        «core/base/source.py»
        # _invalidation_callbacks: list
        # _available: bool
        + available → bool (property)
        + scan() → Iterable[D] (abstract)
        + start() async
        + stop() async
        + invalidate() … sets available=False, fires callbacks
        + restore() … sets available=True
    }

    class ToolSource {
        «components/tool.py»
        + invoke(descriptor, kwargs, ctx) async → object
    }
    Source <|-- ToolSource : extends (binds D=ToolDescriptor)

    class PythonSource~D~ {
        «core/base/source.py»
        - _scope: list[str]
        + set_scope(scope)
        ──────────────────────────────────
        Inherits: scan, invalidate, restore, available
        Adds: modules scope, identity filtering via __module__
    }
    Source <|-- PythonSource : extends

    class PythonToolSource {
        «components/tool.py»
        ──────────────────────────────────
        Scopes: modules with @tool → TOOL_ATTRIBUTE
    }
    PythonSource <|-- PythonToolSource : D=ToolDescriptor

    class PythonHookSource {
        «components/hook.py»
        ──────────────────────────────────
        Scopes: modules with @Hook → HOOK_ATTRIBUTE
    }
    PythonSource <|-- PythonHookSource : D=HookDescriptor

    class PythonInstructionSource {
        «components/instruction.py»
        ──────────────────────────────────
        Scopes: modules with @instruction → INSTRUCTION_ATTRIBUTE
    }
    PythonSource <|-- PythonInstructionSource : D=InstructionDescriptor

    class PythonConnectorSource {
        «components/connector.py»
        ──────────────────────────────────
        Scopes: modules with Connector subclasses → CONNECTOR_ATTRIBUTE
    }
    PythonSource <|-- PythonConnectorSource : D=ConnectorDescriptor

    class PythonServiceSource {
        «core/base/source.py»
        ──────────────────────────────────
        Unified service source. Defaults to SERVICE_ATTRIBUTE/AbstractService/"service".
        Accepts base_type, marker_attribute, id_prefix for provider slots.
    }
    PythonSource <|-- PythonServiceSource : D=ServiceDescriptor

    class Descriptor {
        «core/base/descriptor.py»
        «frozen dataclass»
        + id: str
        + _source_ref: weakref
        + fingerprint → str (property)
        ──────────────────────────────────
        SHA-256(fingerprint_payload) → change detection
    }

    class ToolDescriptor {
        «components/tool.py»
        + namespace: str
        + alias: str
        + name: str
        + exported_name: str
        + doc: str
        + schema: dict
        + metadata: dict
    }
    Descriptor <|-- ToolDescriptor

    class HookDescriptor {
        «components/hook.py»
        + event: str
        + priority: int
        + metadata: dict
    }
    Descriptor <|-- HookDescriptor

    class InstructionDescriptor {
        «components/instruction.py»
        + name: str
        + module: str
        + priority: int
        + before: tuple[str, ...]
        + after: tuple[str, ...]
    }
    Descriptor <|-- InstructionDescriptor

    class ServiceDescriptor {
        «core/base/service.py»
        + service_cls: type[AbstractService]
        + metadata: dict
    }
    Descriptor <|-- ServiceDescriptor

    class ConnectorDescriptor {
        «components/connector.py»
        + connector_cls: type[Connector]
    }
    ServiceDescriptor <|-- ConnectorDescriptor
```

**How descriptors & sources connect:**

```
PythonToolSource      (components/tool.py)      ──scan()──▶ ToolDescriptor       ──▶ ToolManager indexes
PythonHookSource      (components/hook.py)      ──scan()──▶ HookDescriptor       ──▶ HookManager groups by event
PythonInstructionSource (components/instruction.py) ──scan()──▶ InstructionDescriptor ──▶ InstructionManager ordered list
PythonConnectorSource (components/connector.py)  ──scan()──▶ ConnectorDescriptor  ──▶ ConnectorManager creates instances
PythonServiceSource   (core/base/source.py)     ──scan()──▶ ServiceDescriptor    ──▶ ServiceInstanceManager / StorageManager / FileStorageManager / LLMAdapterManager
```

Each source is mounted into an `Manager` subclass. The manager calls `source.scan()` which produces descriptors. The manager's `_rebuild()` then builds specialized indexes (event→handlers map, alias→name→descriptor maps, instance reconciliation sets).

```
ToolManager  ──mount(PythonToolSource)──▶ PythonToolSource (components/tool.py) ──scan()──▶ [ToolDescriptor, ...]
HookManager  ──mount(PythonHookSource)──▶ PythonHookSource (components/hook.py) ──scan()──▶ [HookDescriptor, ...]
InstructionManager ──mount(PythonInstructionSource)──▶ PythonInstructionSource (components/instruction.py) ──scan()──▶ [InstructionDescriptor, ...]
```

Each `Source` tracks its own `available` flag. When a source is invalidated (e.g. module removed from scope), its descriptors are removed from the manager, triggering index rebuild and `on_change` notification.

---

## 9. Agent Run Loop — Response Processing

```mermaid
sequenceDiagram
    participant Agent
    participant HM as HookManager
    participant Conn as Connector
    participant Storage
    participant TM as ToolManager

    loop LLM iteration
        Agent->>Agent: _call_llm()
        Note over Agent: load_dialog → before_llm → ask_llm → after_llm → validate
        Agent-->>Agent: LLMResponse (blocks + meta)

        Agent->>Agent: _process_response()

        loop for each response block
            Agent->>Agent: block.to_dialog_item(meta propagated)
            Agent->>HM: fire(BEFORE_SEND, ctx)
            Agent->>Conn: send(origin, dialog_item)
            alt delivered
                Conn-->>Agent: external_id
                Agent->>Agent: dialog_item.external_id = id
            else not displayed
                Conn-->>Agent: "" (empty string)
                Note over Agent: still persisted below
            end
            Agent->>Storage: save_event(dialog_item)
            Storage-->>Agent: item_id
            Note over Agent: reasoning, text, tool_call blocks<br/>all stored in original order
        end

        loop for each tool call block
            Agent->>Agent: ToolCall(tool_call_id, name, args)
            Agent->>HM: fire(BEFORE_TOOL_CALL, ctx)
            alt aborted
                Agent->>Agent: ToolCallResult.aborted()
            else
                Agent->>TM: call(tool_call, ctx)
                TM-->>Agent: ToolCallResult
            end
            Agent->>HM: fire(AFTER_TOOL_CALL, ctx)
            Agent->>Agent: DialogItem(TOOL_CALL_RESULT)
            Agent->>Conn: send(origin, result_item)
            Agent->>Storage: save_event(result_item)
            Storage-->>Agent: item_id
        end

        alt tools were called
            Agent->>Agent: continue (next LLM iteration)
        else no tools
            Agent->>Agent: return (end run)
        end
    end
```

Key differences from the previous flow:
- Every response block (reasoning, text, tool_call) is **sent through the connector** — the connector decides what to render.
- All blocks are **persisted in order** before any tool executes.
- Tool results also pass through the connector.
- Provider-specific metadata (`meta["llm"]`) is preserved across send/store cycles.
