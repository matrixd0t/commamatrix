# Tools

A tool is a top-level function marked with `@tool`. Its signature and type
annotations become the JSON schema shown to the LLM. Its docstring becomes the
tool description.

```python
from commamatrix import tool


@tool(alias="weather")
async def current(city: str, units: str = "metric") -> dict:
    """Return the current weather for a city."""
    return {"city": city, "units": units, "temperature": 20}
```

Use `async def` for network, filesystem, database, and other I/O. Synchronous
tools are invoked directly on the event loop and are not moved to a thread pool
by the framework or CodeAct.

## Context Injection

The current `BeforeToolCallCtx` can be injected into a tool parameter. Prefer
the annotation:

```python
from commamatrix import BeforeToolCallCtx, tool
from my_project.weather import WeatherService


@tool(alias="weather")
async def forecast(city: str, ctx: BeforeToolCallCtx) -> dict:
    """Get a forecast through the configured weather service."""
    service = ctx.run.agent.services.require(WeatherService)
    return await service.forecast(city)
```

An unannotated parameter named `ctx` is also injected. Injected parameters are
removed from the generated JSON schema and must not be passed by the model.

`ctx.run.tools` is the in-process facade for calling another active tool:

```python
from commamatrix import BeforeRunCtx, before_run


@before_run
async def collect_status(ctx: BeforeRunCtx) -> None:
    result = await ctx.run.tools.project.current_status()
    ctx.run.state["status"] = result
```

The call returns the raw Python result and does not create tool-call dialog
items. `run.tools` exists only in contexts carrying a `RunCtx`; it is not
available in `OnAgentStartCtx` or `OnParsedCtx`.

## Names and Aliases

The module name and tool alias are separate concepts.

```text
my_project/filesystem_tools.py
@tool(alias="fs")
read_file(...)
```

The normal in-process call is:

```python
await ctx.run.tools.fs.read_file(path="README.md")
```

If no alias is provided, the alias defaults to the module's final component.
`@tool(alias="")` exposes the function without a group, so its public name is
the function name and it can be called as `run.tools.function_name(...)`.

For grouped tools, the public name sent to the LLM is `alias_name`, such as
`weather_current`. Two active tools with the same public name are ambiguous and
raise `AmbiguousToolError` instead of being selected silently. Use explicit,
stable aliases for reusable tools; aliases must be valid Python identifiers.

CodeAct's virtual `tools` imports have additional behavior. Read `codeact.md`
when the tool is intended for generated Python code.

## Metadata

Keyword arguments to `@tool` are declarative metadata. A hook can inspect them
through `ToolDescriptor.meta` and filter the tools visible to a particular LLM
call:

```python
from commamatrix import BeforeLlmCallCtx, before_llm_call, tool


@tool(alias="crm", category="private")
async def find_customer(email: str) -> dict:
    """Find a customer in the CRM."""
    ...


@before_llm_call
async def hide_private_tools(ctx: BeforeLlmCallCtx) -> None:
    if not ctx.run.state.get("crm_allowed"):
        ctx.tools = [
            item for item in ctx.tools
            if item.meta.get("category") != "private"
        ]
```

Define the actual tool in the module that is being scanned. Importing a tool
from another module into a package initializer does not make the re-export a
second tool declaration.

See [components/tool.py](../../../components/tool.py) and
[components/hook.py](../../../components/hook.py) for descriptor, schema, and
context details.



