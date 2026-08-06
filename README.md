<img src="logo.svg" alt="CommaMatrix logo" width="256">

# CommaMatrix

CommaMatrix is an async-native Python framework for building conversational
agents. It separates transport connectors, LLM adapters, persistence, tools,
hooks, instructions, and agent-owned services into explicit extensions that
can be composed per agent.

The package targets Python 3.13 and later.

## Features

- Async agent lifecycle with transactional startup, refresh, and shutdown.
- HTTP connector with a web UI, authentication, streaming, and file uploads.
- OpenAI-compatible, OpenAI Responses, and Anthropic Messages HTTP protocols.
- Persistent conversation history with SQLite, PostgreSQL, or a custom storage.
- Discoverable tools, hooks, instructions, services, tables, and connectors.
- Optional web search, CodeAct execution, planner, subagents, and MCP support.
- Per-agent extension scopes instead of a process-wide plugin registry.

## Installation

The commands below use [uv](https://docs.astral.sh/uv/), which manages the
virtual environment, dependencies, and command execution. Install uv first if
it is not available on your system.

Create a virtual environment with Python 3.13 or newer:

```bash
uv venv --python 3.13
```

### Recommended installation

Install the complete built-in integration set. This is the recommended
installation for trying CommaMatrix or building a first agent:

```bash
uv pip install "commamatrix[all]"
```

The `[all]` extra installs optional dependencies. It does not automatically
enable every integration in every agent. Extensions are still activated
explicitly in application code, which keeps each agent's runtime scope
predictable.

### Feature-specific installation

The core package can be installed without optional integrations:

```bash
uv add commamatrix
```

Core runtime dependencies are `pydantic`, `httpx2>=2.9.1,<3`, and
`matrix-fn-schema>=0.1.9`. Optional integrations are kept in extras so an
application can choose its dependency footprint.

Install only the extras used by an application when the complete set is not
needed:

| Extra | Provides |
| --- | --- |
| `dotenv` | Loading configuration from `.env` files |
| `sqlite` | Built-in async SQLite storage |
| `http` | HTTP connector, web UI, authentication, and ASGI server |
| `web` | Web search and page extraction tools |
| `codeact` | CodeAct execution support |
| `planner` | Scheduled tasks and planner integration |
| `postgres` | PostgreSQL storage support |
| `mcp` | Model Context Protocol client support |
| `all` | All built-in integration dependencies |
| `test` | Test runner plus most integration dependencies |

The declared dependency groups are:

| Group | Packages |
| --- | --- |
| Core | `pydantic`, `httpx2>=2.9.1,<3`, `matrix-fn-schema>=0.1.9` |
| `dotenv` | `python-dotenv` |
| `sqlite` | `aiosqlite` |
| `http` | `sse-starlette>=3.3,<4`, `starlette`, `uvicorn`, `bcrypt`, `PyJWT`, `python-multipart` |
| `web` | `ddgs>=9.14.4`, `trafilatura>=2.1.0` |
| `codeact` | `bm25s` |
| `planner` | `matrix-planner>=0.2.1` |
| `postgres` | `asyncpg` |
| `mcp` | `mcp>=2.0.0` |

For example:

```bash
uv pip install "commamatrix[http,sqlite]"
```

## Quickstart

The following example starts an authenticated HTTP agent backed by an
OpenAI-compatible API. The same adapter can be configured for other supported
providers by changing `LLM_API_BASE`, `LLM_API_PROTOCOL`, and the API key
field.

Set the provider configuration in the environment. CommaMatrix also loads a
`.env` file when `python-dotenv` is installed:

```bash
export OPENAI_API_KEY="your-api-key"
export LLM_API_BASE="https://api.openai.com"
```

On Windows PowerShell:

```powershell
$env:OPENAI_API_KEY = "your-api-key"
$env:LLM_API_BASE = "https://api.openai.com"
```

Create `quickstart.py`:

```python
import asyncio
import os

from commamatrix import *


async def main() -> None:
    agent = Agent(name="my_lovely_assistant")
    await agent.add_extensions(presets.minimal)

    # See every ConfigField declared by the two active extensions.
    print(agent.config_fields_info())

    agent.config.set(agentic_model, "deepseek-v4-flash")
    agent.config.set(api_base, os.environ["LLM_API_BASE"])
    agent.config.set(openai_api_key, os.environ["OPENAI_API_KEY"])

    # __aenter__ starts the agent; __aexit__ stops it reliably on exit.
    async with agent:
        print(f"CommaMatrix is running at {agent.http_server.base_url}")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
```

`async with agent` starts the agent and always stops it when the block exits,
including cancellation from `Ctrl+C`. If the application has no work to do
between startup and shutdown, the same lifecycle can be shortened to:

```python
await agent.run_forever()
```

Start it with uv:

```bash
uv run quickstart.py
```

Open `http://127.0.0.1:8338/commamatrix` in a browser. On the first start, the HTTP connector creates an administrator account and prints its generated password once. Save that password. The default SQLite database and uploaded files are stored at `.commamatrix/`.

The health endpoint does not require authentication:

```bash
curl http://127.0.0.1:8338/commamatrix/health
```

For a non-interactive request, log in first and use the returned bearer token:

```bash
curl -X POST http://127.0.0.1:8338/commamatrix/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"YOUR_ADMIN_PASSWORD"}'
```

Then send a message with the token returned as `access_token`:

```bash
curl -X POST http://127.0.0.1:8338/commamatrix/api/messages \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"Explain what CommaMatrix does in one sentence."}'
```

The response contains the new dialog items, including the assistant output. For streaming, add `?stream=1` to the messages endpoint and consume events from `/commamatrix/api/events`.

`agent.config_fields_markdown()` returns Markdown sections for the currently active extension modules. Each field is rendered as `## name: type (default: value)`, followed by its declaring module and description; the parenthesized default is omitted when no default is declared. Defaults created by a callable are shown as `computed`; configuration values are never included in the output. Call the helper after `add_extensions()` and before `start()` when you want to inspect only the extensions selected by the application. Core fields such as `agentic_model`, `http_host`, and `http_port` are not extension fields and can be imported and configured separately as shown above.

## Configuration

The LLM HTTP adapter reads these environment variables by default:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Key for OpenAI-compatible and OpenAI Responses APIs |
| `ANTHROPIC_API_KEY` | Key for the Anthropic Messages API |
| `LLM_API_BASE` | Provider base URL |
| `LLM_API_PROTOCOL` | `chat_completions`, `responses`, or `anthropic_messages` |

The provider must expose a compatible models endpoint. The adapter discovers available models during startup, and `agentic_model` filters the discovered models by substring. The quickstart selects `deepseek-v4-flash`; replace that value with a model available from your provider.

Configuration fields are ordinary Python objects and can be passed as keys in an agent's `config` dictionary on init:

```python
from commamatrix import *

agent = Agent(
    "my-agent",
    config={
        agentic_model: "my-model",
        api_base: "https://llm.example.com",
    },
)
```

## Extensions

Extensions are imported and then added to an agent's scope. The recommended preset lists containig built-in features are available in `commamatrix.presets`:

```python
from commamatrix import Agent
from commamatrix.presets import assistant


async def create_agent() -> Agent:
    agent = Agent("my_lovely_assistant")
    await agent.add_extensions(assistant)
    return agent
```

Individual extensions can be selected when an agent needs a narrower scope:

```python
from commamatrix.builtin import data_tools, web_utils

await agent.add_extensions(data_tools, web_utils)
```

Custom or external extensions can expose normal Python declarations and be activated by import name:

```python
await agent.add_extensions("my_project.my_extension")
```

Common declarations include `@tool`, `@instruction`, lifecycle hooks, service subclasses, provider implementations, and `BaseTable` subclasses. See the [extension authoring guide](https://github.com/matrixd0t/commamatrix/blob/master/src/commamatrix/builtin/self_extension/guides) for the complete extension API.

## Security Notes

- Keep `http_host` set to `127.0.0.1` for local development. `0.0.0.0` exposes your HTTP connector to the Internet.
- HTTP connector passwords are hashed; generated administrator credentials are printed only during initial account creation.
- CodeAct executes arbitrary Python code with access to the standard library, installed dependencies, and the system terminal. Default subprocess backend is intentionally NOT a security sandbox and must NOT be exposed to untrusted users without an external isolation layer. To enforce configurable limits on the agent’s execution privileges, prefer systemd or Docker-backed implementations.
- Validate the reverse proxy, TLS, CORS, and network policy before exposing the HTTP connector to the Internet.

