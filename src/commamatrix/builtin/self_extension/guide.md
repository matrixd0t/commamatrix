# CommaMatrix Extension Guide

This guide explains how to write an extension or a third-party integration for
an agent that can modify its own runtime.

## Public API

The public component API is re-exported from the package root. `Agent(auto_load_plugins=True)` automatically activates existing files and package directories in `<CWD>/.commamatrix/plugins` at startup; pass `auto_load_plugins=False` to opt out. For a quick extension, this is supported:

```python
from commamatrix import *
```

Explicit imports are also fine. 

Useful source files for the exact API are:

The Markdown targets below are relative to this guide file. For example, the tool implementation is at
`<commamatrix_path>/components/tool.py`.

- [components/tool.py](../../components/tool.py) - tools, schemas, aliases, and tool invocation.
- [components/hook.py](../../components/hook.py) - hook decorators and every hook context.
- [components/instruction.py](../../components/instruction.py) - instructions and system prompt assembly.
- [components/config.py](../../components/config.py) - `ConfigField` and per-agent configuration.
- [components/connector.py](../../components/connector.py) - platform connectors.
- [components/dialog.py](../../components/dialog.py) - origins and dialog items.
- [components/llm_adapter.py](../../components/llm_adapter.py) - LLM blocks and provider adapters.
- [components/table.py](../../components/table.py) - plugin-owned tables, schema discovery, and migrations.
- [core/classes/service.py](../../core/classes/service.py) - service lifecycle and discovery.
- [core/agent/agent.py](../../core/agent/agent.py) - extension activation and the agent run loop.

## Runtime Workflow

Keep self-written extensions outside the installed framework. 
The runtime reserves `<CWD>/.commamatrix/plugins` for this purpose and creates it when an agent starts with `auto_load_plugins=True` (the default). 
Do not spend a tool call creating this directory.

When a new `Agent` starts, `auto_load_plugins=True` (the default) automatically
activates every direct `.py` file and every direct package directory in
`<CWD>/.commamatrix/plugins`. A package should import its contribution modules
from `__init__.py`; nested implementation files are not imported just because
they exist. Disable this behavior with `Agent(auto_load_plugins=False)` when
the host must activate extensions explicitly; with it disabled the plugins
directory is not created automatically either. Files created during the current
run still need `manage_extension(action="add")`; automatic discovery applies when an agent
starts.

```text
<CWD>/
    .commamatrix/
        plugins/
            response_style.py
            weather/
                __init__.py
                tools.py
```

Prefer the smallest implementation that solves the task:

1. Create one `.py` file in `.commamatrix/plugins`, or a package for a genuinely larger extension.
2. Put discoverable functions and classes at module level.
3. Check imports and required third-party packages.
4. Use `manage_extension(action="add", module_or_path=".commamatrix/plugins/response_style.py")` when the current agent must use a newly created file immediately.
5. Test the new capability. Reload it after editing and remove it when no longer needed.

`module_or_path` accepts either an import name or a relative/absolute Python
path. A path is resolved to its canonical import name before activation, so the
runtime does not create synthetic module names. Use the same target form for
reloads; the result reports the canonical module name that is active.

The extension scope belongs to one `Agent`. Activation refreshes all managers
and starts newly discovered services and connectors. Removing an extension
removes its descriptors and stops its owned services and connectors. It does
not delete source files or uninstall dependencies.

All built-in plugins are optional. Core components are part of the framework,
but a particular built-in plugin may not be active. Do not assume that one is
loaded unless the current tool set or application configuration confirms it. A
normal extension should depend only on the core API and on libraries that are
actually installed.

## Extension Size and Layout

Keep an extension in one file while it is reasonably understandable. As a
practical rule, a plugin up to about 500-600 lines should normally remain a
single file. Split it into a package only when it is clearly larger, has
independent subsystems, or a package layout materially improves maintenance.
Do not create `config.py`, `hooks.py`, `service.py`, and `tools.py` just to wrap
a small feature.

Default layout. The `.commamatrix/plugins` directory is created automatically
before the first run:

```text
<CWD>/
    .commamatrix/
        plugins/
            response_style.py
            weather.py
```

Optional package layout for a genuinely larger extension:

```text
.commamatrix/plugins/my_extension/
    __init__.py
    config.py
    service.py
    tools.py
    hooks.py
    instructions.py
    connector.py
```

`my_extension/__init__.py` must import the submodules that contain extension
objects:

```python
# .commamatrix/plugins/my_extension/__init__.py

from . import config, connector, hooks, instructions, service, tools
```

Adding a package discovers submodules that have been imported. Merely creating
`tools.py` is not enough if `__init__.py` never imports it. The source scanner
ignores private names and ignores re-exports whose `__module__` points to
another module. Define the actual extension object in its own module and import
that module from the package initializer.

Do not put a discoverable tool inside a class as a method. Python sources scan
module globals, not arbitrary class members. Define tools, hooks, and
instructions as top-level functions, and define service and connector classes
as top-level classes.

Do not make network calls, start tasks, or open files at import time. Importing
an extension only declares it. Allocate resources in `start()` and release
them in `stop()`.

## Choose the Smallest Extension Point

- Change response style or add dynamic prompt text: use one `@instruction`.
- Change a lifecycle event or filter tools: use one hook.
- Add an action the agent can call: use one `@tool`.
- Keep a long-lived external client: add a `Service` only when needed.
- Integrate a messaging platform: add a `Connector`.
- Persist structured plugin-owned data: declare a `BaseTable`.
- Replace persistence or the LLM provider: implement the corresponding provider.

### Persist Reusable Behavior

If a behavior is useful beyond the current task, add it to the agent instead of
relying on the model to remember it. This is a deliberate self-improvement
choice, not something to do for every one-off detail:

- A reusable response rule, workflow rule, or always-needed piece of context belongs in an `@instruction`. It returns text that is added to the system prompt before future LLM calls.
- A reusable action, integration, or capability belongs in an `@tool`. The agent can call it when the capability is needed.
- Store the implementation in `.commamatrix/plugins`, then activate or reload it for the current agent. With `auto_load_plugins=True` in parent app, anything from this folder is loaded as extensions on agent startup.
- Do not persist a temporary fact or a rule that only applies to the current request.

Example of a persistent instruction:

```python
# .commamatrix/plugins/agent_rules.py
from commamatrix import InstructionCtx, instruction


@instruction
def concise_answers(_ctx: InstructionCtx) -> str:
    return "Prefer direct answers with only the detail needed for the task."
```

Example of a persistent tool:

```python
# .commamatrix/plugins/project_tools.py
from commamatrix import tool


@tool(alias="project")
async def current_status() -> str:
    """Return the current project status."""
    return "..."
```

For the current run, use the `self_extension` tools to create the file and then
call `manage_extension`. The `self_extension` module itself also
provides this guidance as an instruction, so the option is available without
reading the guide manually.

For example, a response style does not need a package, service, configuration
layer, or LLM parameter hook unless those features are explicitly required:

```python
# .commamatrix/plugins/response_style.py

from commamatrix import InstructionCtx, instruction


@instruction(priority=100)
def response_style(ctx: InstructionCtx) -> str:
    """Apply the agent's concise technical response style."""
    return (
        "Response style: be direct, technically precise, and concise. "
        "Prefer short paragraphs and focused code examples. Do not add "
        "decorative roleplay, filler, or unnecessary sections."
    )
```

## Tools

A tool is a top-level function decorated with `@tool`:

```python
# .commamatrix/plugins/weather.py

from commamatrix import tool


@tool(alias="weather")
async def current(city: str, units: str = "metric") -> dict:
    """Return the current weather for a city."""
    return {"city": city, "units": units, "temperature": 20}
```

The signature and type hints become the JSON schema shown to the LLM. The function docstring becomes its description. Use `async def` for network, filesystem, database, and other I/O. A synchronous tool runs directly on the event loop, so blocking synchronous code can stall the whole agent.

The framework can inject the current `BeforeToolCallCtx` into a tool parameter.
Use the annotation when possible:

```python
from commamatrix import BeforeToolCallCtx, tool

from .service import WeatherService


@tool(alias="weather")
async def forecast(city: str, ctx: BeforeToolCallCtx) -> dict:
    """Get a weather forecast from the configured weather service."""
    service = ctx.run.agent.services.require(WeatherService)
    return await service.forecast(city)
```

Parameter is also injected when it is named `ctx` with no annotation. The exact injection and schema rules are implemented in [components/tool.py](../../components/tool.py). The `BeforeToolCallCtx` definition and the complete `RunCtx` are in[components/hook.py](../../components/hook.py); read those files when the extension needs context fields not shown here.

There is no strict JSON-only return requirement for every tool. The framework serializes ordinary results for dialog and tool-result transport, while a specialized tool may intentionally return bytes or another value for its consumer. For a normal LLM-facing tool, prefer a concise string, number, boolean, list, dict, or another value with an unambiguous serialization.

### Tool Names, Aliases, and CodeAct Imports

`alias` is the tool group's **import name** in the CodeAct worker. It is the part that appears after `tools.`. The extension module name and the tool alias are different things and must not be confused:

```text
.commamatrix/plugins/filesystem_tools.py  ->  Python module: filesystem_tools
@tool(alias="fs")                      ->  CodeAct import: import tools.fs as fs
```

Read the `@tool(alias="...")` in the source or use `list_tools` / `search_tools` to find the alias.

```python
import tools.fs as fs

content = await fs.read_file(path="README.md")
```

Do not derive the import from the extension filename when an explicit alias is
present. In particular, do not replace `fs` with `filesystem_tools` merely
because the file is named `filesystem_tools.py`.

The public tool names and imports are computed as follows:

- `@tool` uses the module's last component as the alias, so a tool in `filesystem_tools.py` defaults to `tools.filesystem_tools`.
- `@tool(alias="weather")` exposes `weather_current` for a function named `current` and imports as `tools.weather`.
- `@tool(alias="")` exposes the bare function name, such as `current`; it is not imported through a grouped `tools.<alias>` module.

For self-written tools, always choose an explicit stable alias that describes
the group and use that alias as the CodeAct import name. Two active tools with
the same public name are ambiguous. The alias must be a valid Python identifier.

Tool metadata is an arbitrary declarative dictionary. A `before_llm_call` hook
can inspect `ToolDescriptor.meta` and filter or annotate `ctx.tools` according
to that metadata:

```python
from commamatrix import BeforeLlmCallCtx, before_llm_call, tool


@tool(alias="crm", category="private", version=1)
async def find_customer(email: str) -> dict:
    """Find a customer in the CRM."""
    ...


@before_llm_call
async def hide_private_tools(ctx: BeforeLlmCallCtx) -> None:
    """Expose private tools only in an approved conversation."""
    if not ctx.run.state.get("crm_allowed"):
        ctx.tools = [item for item in ctx.tools if item.meta.get("category") != "private"]
```

The exact descriptor fields are documented in
[components/tool.py](../../components/tool.py), and the fields of
`BeforeLlmCallCtx` are documented in [components/hook.py](../../components/hook.py).

## Hooks

Hooks are top-level functions decorated with one of these lifecycle
decorators:

- `on_agent_start`
- `on_parsed`
- `before_run`
- `before_llm_call`
- `after_llm_call`
- `before_tool_call`
- `after_tool_call`
- `before_send`
- `on_error`
- `after_run`

They may be synchronous or asynchronous. Prefer asynchronous hooks when they
perform I/O:

```python
from commamatrix import BeforeLlmCallCtx, before_llm_call


@before_llm_call
async def choose_model(ctx: BeforeLlmCallCtx) -> None:
    """Choose a llm for a particular user or conversation."""
    if ctx.run.state.get("use_fast_model"):
        ctx.run.model = "openai/gpt-4o-mini"
```

Use the hook context matching the decorator. To inspect exact context fields,
mutability, and event semantics, read
[components/hook.py](../../components/hook.py). To understand when each event
fires in the full run, read [core/agent/agent.py](../../core/agent/agent.py).

Hooks in one event are ordered by `before` and `after` constraints first, then
by `priority`; higher priority runs earlier. Equal-priority unconstrained hooks
keep declaration order. Use a callable or a name in constraints:

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

Avoid cycles in `before` and `after`; a cycle prevents manager refresh from
completing. Unknown constraint names are ignored, so direct callable references
are preferable within one module.

## Instructions

Instructions generate fragments of the system prompt. They run before every
LLM call; non-`None` results are joined with blank lines and prepended as a
`SYSTEM` `DialogItem`. They are not persisted as normal conversation history.

```python
from datetime import datetime, timezone

from commamatrix import InstructionCtx, instruction


@instruction(priority=10)
def current_time(ctx: InstructionCtx) -> str:
    """Give the llm the current UTC date."""
    now = datetime.now(timezone.utc)
    return f"Current UTC time: {now:%Y-%m-%d %H:%M}"
```

An instruction receives `InstructionCtx` and returns `str | None`. Return
`None` when no fragment is needed. Instructions support `priority`, `before`,
and `after`; higher priority runs earlier. The complete implementation and the
built-in system-message hook are in
[instruction.py](../../components/instruction.py).

## Configuration and Third-Party Libraries

Declare configuration fields at module level. A field object, not its string
name, is the key in `Agent.config`:

```python
# my_extension/config.py

import os

from commamatrix import ConfigField

api_key = ConfigField[str](name="my_extension.api_key", default=lambda: os.getenv("MY_EXTENSION_API_KEY", ""), description="API key for the external service")
request_timeout = ConfigField[float](name="my_extension.request_timeout", default=20.0, description="HTTP timeout in seconds")
```

Read fields through `self.config.get(field)` or
`ctx.run.agent.config.get(field)`. Overrides take precedence over defaults:

```python
from commamatrix import Agent
from my_extension.config import api_key, request_timeout

agent = Agent(config={api_key: "secret", request_timeout: 10.0})
```

A field without a default fails when it is first read if no override was
provided. Never put API keys in source code, tool docstrings, metadata, or
dialog content. Prefer environment-backed defaults or host-provided
configuration. See [components/config.py](../../components/config.py) for the
full resolution rules.

An external library must be importable before activation. If it is not already
a project dependency, install it in the host environment. Do not silently
replace a real dependency with a fake fallback.

A useful pattern is a `Service` that owns the external client and a tool that
retrieves that service:

```python
# my_extension/service.py

from __future__ import annotations

import httpx

from commamatrix import Service

from .config import api_key, request_timeout


class WeatherService(Service):
    def __init__(self, agent) -> None:
        super().__init__(agent)
        self._api_key = self.config.get(api_key)
        self._timeout = self.config.get(request_timeout)
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=self._timeout)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def refresh(self) -> None:
        return

    async def forecast(self, city: str) -> dict:
        if self._client is None:
            raise RuntimeError("WeatherService is not started")
        response = await self._client.get("https://example.invalid/weather", params={"city": city}, headers={"Authorization": f"Bearer {self._api_key}"})
        response.raise_for_status()
        return response.json()
```

`Service` instances receive the current agent and follow this lifecycle:

- `start()` allocates resources when the extension becomes active.
- `refresh()` synchronizes an active instance after extension changes and may be called often.
- `stop()` releases resources when the extension is removed or the agent stops.

All lifecycle methods should be idempotent where practical. A custom service
should subclass `Service`, not `AbstractService`, so the normal service manager
discovers it. Access a running service with
`ctx.run.agent.services.get(MyService)` or `require(MyService)`. See
[core/classes/service.py](../../core/classes/service.py) and
[core/classes/manager.py](../../core/classes/manager.py).

## Connectors

A connector translates an external platform into `DialogItem` objects and
renders outgoing items back to that platform. Define a platform-specific
`DialogOrigin` and a generic connector:

```python
# my_extension/connector.py

from commamatrix import Connector, DialogItem, DialogItemType, DialogOrigin, DialogRole, OnParsedCtx


class ChatOrigin(DialogOrigin):
    platform: str = "my_chat"
    chat_id: str


class ChatConnector(Connector[ChatOrigin]):
    async def parse(self, data: dict) -> OnParsedCtx | None:
        if data.get("platform") != "my_chat":
            return None
        origin = ChatOrigin(chat_id=str(data["chat_id"]))
        item = DialogItem(content=str(data["content"]), item_type=DialogItemType.INPUT, role=DialogRole.USER, origin=origin, user=str(data.get("user", "unknown")))
        return OnParsedCtx(agent=self.agent, connector=self, raw=data, dialog_items=[item], previous_external_id=data.get("previous_external_id"))

    async def send(self, origin: DialogOrigin, item: DialogItem) -> str:
        if not isinstance(origin, ChatOrigin):
            return ""
        # Render item according to item.item_type and send it to the platform.
        return "my-chat-message-id"

    async def listen(self, on_recv) -> None:
        # Read events from the third-party client and call await on_recv(raw_event).
        return
```

Connectors are discovered automatically and every discovered connector is
active. `Connector[ChatOrigin]` lets the framework infer `origin_types`. The
base connector starts `listen(self.agent.handle)` as a task. Override
`listen()` for polling or webhook loops, and override `start()` or `stop()` only
when the third-party client needs additional lifecycle handling.

`send()` receives every complete outgoing block, including reasoning, text,
images, files, and tool calls. The connector decides what its platform can
render. It must return an external ID or an empty string; the agent persists
the dialog item even when delivery has no external ID.

For live streaming, set `supports_streaming = True` and implement
`send_stream_chunk(origin, chunk)` when the platform supports partial updates.
Streaming chunks are real-time only; complete blocks still arrive through
`send()` and are persisted. See [components/connector.py](../../components/connector.py),
[components/dialog.py](../../components/dialog.py), and the built-in
[http_connector/connector.py](../http_connector/connector.py).

## Plugin-Owned Tables

A plugin can opt into the active structured storage by declaring a `BaseTable`.
The row schema is a Pydantic model; the table declaration is a separate class.
No ORM is required.

```python
# .commamatrix/plugins/audit.py
from pydantic import BaseModel

from commamatrix import BaseTable


class AuditRow(BaseModel):
    id: str
    event: str
    created_at: str


class AuditTable(BaseTable[AuditRow]):
    table_id = "audit.events"
    table_name = "audit_events"
    row_model = AuditRow
    primary_key = "id"
    indexes = (("event",),)
    version = 1
```

`TableManager` discovers `BaseTable` subclasses from the active extension scope.
It runs after `StorageManager` selects the active storage and before plugin
services start. A plugin service can therefore use its table from `start()`.
SQL storage initializes `commamatrix_schema_versions` automatically, creates
missing tables and indexes, and records each table's logical ID and version.

Schema changes require an explicit version increase and migration:

```python
class AuditTable(BaseTable[AuditRow]):
    table_id = "audit.events"
    table_name = "audit_events"
    row_model = AuditRow
    version = 2

    @classmethod
    async def migrate(cls, backend, from_version: int) -> None:
        if from_version < 2:
            await backend.add_column(cls.table_name, "source", "TEXT")
```

`ensure_table()` applies the current table version and rejects downgrades. Do
not rely on Pydantic field changes to infer renames or destructive migrations.
Removing a plugin does not drop its table or its data. Use a stable explicit
`table_id`; `table_name` must be a valid SQL identifier and must not collide with
another active plugin table.

A custom storage that supports plugin tables must expose a `schema_backend` with
`ensure_table()` and the migration operations required by its table classes.
A storage without this capability cannot activate extensions that declare tables.

## Scheduled Tasks

Declare tasks in a persistent plugin file under `.commamatrix/plugins`:

```python
from commamatrix import DialogItem, DialogItemType, DialogRole, InternalOrigin, ScheduledTaskContext, cron, task

@task(cron("0 12 * * 1"))
async def weekly_digest(ctx: ScheduledTaskContext) -> None:
    await ctx.submit_run(
        dialog_items=[
            DialogItem(
                content="Сформируй еженедельный дайджест",
                item_type=DialogItemType.INPUT,
                role=DialogRole.USER,
                origin=InternalOrigin(task_id=ctx.task_id),
                user="any_identity_alias",
            )
        ]
    )
```

Use `cron(...)`, `every(...)`, or `once(datetime(...))`; these helpers are
re-exported by `commamatrix.builtin.scheduler`. The task ID is always
`<module>:<function>`, so function names must be unique within a module.
Tasks are discovered from active extensions, added and removed on extension
reload, and recreated after restart. Missed cron/interval runs are skipped;
a past `once(...)` task runs immediately when the service starts. To continue
an existing stored branch, call `ctx.submit_run(last_item_id=item_id)` instead
of passing new `dialog_items`.

## Storage, File Storage, and LLM Providers

Only implement a provider when a built-in provider is insufficient.

A custom `Storage` must implement:

```python
class MyStorage(Storage):
    async def save_event(self, entry: DialogItem) -> int | None: ...
    async def get_branch(self, last_item_id: int) -> list[DialogItem]: ...
    async def find_item_id_by_external_id(self, external_id: str, origin: DialogOrigin) -> int | None: ...
    async def get_history(self, *, origin_type=None, origin_fields=None) -> list[DialogItem]: ...
```

A custom `FileStorage` implements `save(data, ext)`, `get(file_id)`, and
`delete(file_id)`. A custom storage provider becomes active automatically as
the first available provider unless the host selects another provider through
configuration.

A custom `LLMAdapter` implements `ask_llm(ctx, stream=False)` as an async
iterator. It yields `LLMResponseBlock` values and finishes with `StreamEnd`.
When streaming, it may yield `StreamDelta` values for live content. Use the
existing text, reasoning, tool-call, image, and file block classes. The manager
currently calls the first discovered LLM adapter.

Provider classes must be concrete, top-level subclasses of their respective
provider base classes. The provider marker is applied automatically. Read
[components/storage.py](../../components/storage.py),
[components/file_storage.py](../../components/file_storage.py), and
[components/llm_adapter.py](../../components/llm_adapter.py) before writing a
provider.

## Dialog Data

The core dialog model uses `DialogItemType` for input, output, media,
reasoning, tool calls, and tool results, and `DialogRole` for system,
developer, user, assistant, and tool messages. A `DialogItem` contains
content, type, role, origin, history links, external ID, and metadata.

Read [components/dialog.py](../../components/dialog.py) for the exact Pydantic
models and fields. Read the storage and LLM adapter implementations before
creating custom media or persistence behavior. Binary content should normally
be stored through `FileStorage` and referenced from a dialog item rather than
embedded into ordinary text.

## Safe Updates

Before activating an extension:

- Make its import path unambiguous.
- Import every contribution submodule from the package initializer.
- Check that imports and required third-party packages are available.
- Keep credentials in configuration or environment variables.
- Use unique tool aliases, hook names, origin class names, and service classes.
- Keep import-time code free of network calls and irreversible side effects.
- Make tools async when they perform blocking external I/O.
- Add authorization, validation, and rate limits for external side effects.

After editing an active extension, reload it using the runtime extension tool.
If a change affects a long-lived resource, ensure the service's `refresh()` or
lifecycle code applies it. After removing an extension, confirm that its tools
are unavailable and that its client, listener, and background tasks stopped.

For the CodeAct mode and its integration-specific behavior, read
[builtin/codeact/service.py](../codeact/service.py), together with `tools.py`,
`hooks.py`, and the executor and RPC modules.

## Minimal Checklist

When adding an integration:

1. Use the automatically created root `.commamatrix/plugins` directory.
2. Prefer one file unless the extension is clearly larger than 500-600 lines or has independent subsystems.
3. Choose the smallest extension point that solves the task.
4. Define `ConfigField` values only when configuration is actually needed.
5. Put external clients and persistent resources in a `Service` only when needed.
6. Verify imports and dependencies.
7. Activate the extension with the runtime `manage_extension` tool.
8. Test it with a harmless input.
9. Reload it after code changes and remove it when no longer needed.
