<h1 align="center"> CommaMatrix</h1>
<p align="center">
  <img src="https://raw.githubusercontent.com/matrixd0t/commamatrix/master/assets/logo.png" alt="CommaMatrix" width="512">
</p>
<p align="center">
  <strong>CRAFT YOUR OWN AI AGENT</strong>
</p>
<p align="center">
  <strong><a href="https://github.com/matrixd0t/commamatrix/blob/master/README.md">Русский</a> | English</strong>
</p>


<p align="center">
  <a href="https://raw.githubusercontent.com/matrixd0t/commamatrix/master/installer/windows/install.ps1">Installer</a>
  ·
  <a href="https://github.com/matrixd0t/commamatrix/blob/master/src/commamatrix/builtin/self_extension/guides/main.md">Documentation</a>
  ·
  <a href="https://github.com/matrixd0t/commamatrix/tree/master/examples/">Examples</a>
</p>


## Are you a Windows user?

Run the minimalist AI agent shipped with CommaMatrix right now using the
instructions below. It is **completely** free and **completely** private: only
your internet provider stands between you and the AI.


### Method 1. Download the file

Download and run [`install.ps1`](https://raw.githubusercontent.com/matrixd0t/commamatrix/master/installer/windows/install.ps1).
Open the downloaded file by double-clicking it.

### Method 2. One command

1. Press `Win + R`.
2. Type `powershell` and press Enter.
3. Paste the command:

```powershell
irm https://raw.githubusercontent.com/matrixd0t/commamatrix/master/installer/windows/install.ps1 | iex
```

4. Choose English language, Basic installation mode, and
   follow the instructions. The application will appear in the system tray,
   from where you can open the chat window in your browser or shut the program down.
   A quick-launch shortcut will appear on your desktop.

Do not forget to save the password. You will be able to change both the name and the
password through the web interface.

### How is this different from ChatGPT?

The agent can do everything you can do on your computer. For example, it can
process 20 photos in **your** Photoshop, compile an evening news digest through
**your** browser, or write a report, save it as a Word document, and send it
from **your** email. No prompts, plugins, or other forms of integration are
needed: the model is **smart enough on its own** for these tasks, while
CommaMatrix's built-in capabilities are comprehensive enough to make it happen.

# Are you a developer?

*CommaMatrix is to an agent what an operating system is to a user.*

If one model is the brain, CommaMatrix is the nervous system.

The library lets you connect any set of components into a coherent system:
brains (LLM adapters), speech and sensory organs (connectors), limbs (tools),
internal organs (lifecycle components), instructions, dialog models and
configuration fields, as well as both internal and business logic (hooks).

CommaMatrix is fully modular. You can replace any library class with your own
implementation, or add your implementation to pre-existing in `commamatrix/builtin`.

Every `builtin` is just a module written with CommaMatrix and shipped alongside
it. That alone should give you a sense of how broad its capabilities are while
keeping the framework simple. Builtins include:

- Ten hooks at different points of the lifecycle, with absolute and relative
  priority mechanisms. Model instructions use the same mechanism, controlling
  their relative positions in the prompt. **All** internal CommaMatrix logic is
  implemented through its hooks.
- An LLM HTTP adapter. CommaMatrix understands everything that speaks
  `chat completions`, `openai requests`, or `anthropic messages`, and you can add
  your own codecs by implementing an `ApiCodec` subclass. You can also implement
  your own `LLMAdapter`, for example to control a local model from inside
  CommaMatrix.
- `CodeAct`: programmable tool calls. Any Python function decorated with
  `@tool` is a model tool, and every model tool, regardless of its source,
  including MCP, is an asynchronous Python function. Add your own tool sources
  by implementing a `ToolSource` subclass, or override the components used by a
  builtin.
- Multi-user and multi-dialog communication. For CommaMatrix, a dialog is any
  unique object capable of accepting, storing, and delivering user messages.
  Implement `DialogOrigin` and `Connector` subclasses. #todo example in examples:
  a cross-platform messenger with AI moderation
- An HTTP connector: talk to the model through a browser chat window and grant
  others access by generating one-time invitation links. HTTP API endpoints are included.
- A task scheduler: create heartbeats for the agent or let it create them on
  its own.
- SQL data storage: the agent can search dialogs, user data, and any
  other information stored in database. SQLite and PostgreSQL work out of the box. If
  your application needs to persist structured data, you should implement a `BaseTable` subclass.
  Want an ORM? Implement your own `Storage` subclass.
- An `httpx2` web client and a minimalist web server built with
  `uvicorn + starlette`. Or you may use something else by implementing a subclass.
- Automatic context injection into tools, instructions, and hooks through a
  `ctx` parameter in `fastapi` style. All contexts are strictly typed and
  contain a reference to the agent instance.
- Web search through `ddgs` (#todo: make the search backend a proper class so
  you can plug in or implement your own), plus reading and writing any kind of
  data over HTTP, from disk, or through an arbitrary file-storage
  implementation. You may implement a `FileStorage` subclass.
- Want something fundamentally new that is not listed here? Implement a
  `Service`, `AbstractService`, `Descriptor`, `Manager`, `Source`, or any of
  their existing subclasses to make your component into CommaMatrix logic and lifecycle.

**The model is responsible for intelligence. CommaMatrix is responsible for
everything else.**

## The whole framework fits in the context window

The CommaMatrix source fits into the context window even for previous-generation
models. **Less than 200k tokens** with all built-in features.

| Metric            | Core, without `builtin` | With `builtin` |
|-------------------|------------------------:|---------------:|
| Tokens            |                 ~48,000 |       ~124,000 |
| Python code lines |                  ~6,000 |        ~16,000 |


## Technical details

CommaMatrix targets **Python 3.13+**. [`uv`](https://docs.astral.sh/uv/) is the
recommended installation and environment manager.

```bash
uv venv --python 3.13
uv add "commamatrix[all]"
```

If you cloned the repository:

```bash
uv sync --extra all
```

### Quickstart

Set the provider configuration. CommaMatrix also loads `.env`:

```bash
export OPENAI_API_KEY="your-api-key"
export LLM_API_BASE="https://api.openai.com"
```


Create `quickstart.py`:

```python
import asyncio
import os

from commamatrix import *
from commamatrix.builtin import llm_http_adapter

async def main() -> None:
    agent = Agent(name="my_lovely_assistant")
    await agent.add_extensions(
        commamatrix.builtin.default_instruction,  # add extensions this way
        llm_http_adapter,  # or this way
        "commamatrix.builtin.http_connector",  # or by module name
    )

    # complete state isolation for every agent

    agent.config.set(llm_api_base, os.environ["LLM_API_BASE"])  # change settings at any time
    agent.config.set(openai_api_key, os.environ["OPENAI_API_KEY"])  # lambda predicates can be passed as values
    agent.config.set(agentic_model, "deepseek-v4-flash")
    # the first substring match is selected for model name
    # for example, 'deepseek/deepseek-v4-flash' matches
    # the most affordable provider has the priority

    async with agent:  # like asynccontextmanager, or use await agent.start() / agent.stop()
        print(f"CommaMatrix agent is running at {agent.http_server.base_url}")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
uv run quickstart.py
```

`async with agent` guarantees that the agent stops correctly when leaving the
block, including cancellation from `Ctrl+C`. If the application has no work to
do between startup and shutdown, use:

```python
await agent.run_forever()
```

### HTTP UI and HTTP connector

Open `http://127.0.0.1:8338/commamatrix`. On the first launch, the HTTP
connector creates an administrator and returns the generated password.

By default, the host is bound to `127.0.0.1`. If you run the application on a
server, switch `http_host` to `0.0.0.0` so the agent can be reached externally.
Add or remove users through the browser page to work on projects together.

#### Custom interface / API access

The health endpoint does not require authentication:

```bash
curl http://127.0.0.1:8338/commamatrix/health
```

For API requests, get a token first:

```bash
curl -X POST http://127.0.0.1:8338/commamatrix/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"YOUR_ADMIN_PASSWORD"}'
```

Then send a message:

```bash
curl -X POST http://127.0.0.1:8338/commamatrix/api/messages \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"Explain what CommaMatrix does in one sentence."}'
```

For an SSE stream, add `?stream=1` to the request and read events from
`/commamatrix/api/events`.

### LLM interaction

The LLM HTTP adapter requires these values by default:

| Variable            | Purpose                                                   |
|---------------------|-----------------------------------------------------------|
| `OPENAI_API_KEY`    | Token for the OpenAI-compatible and OpenAI Responses APIs |
| `ANTHROPIC_API_KEY` | Token for the Anthropic Messages API                      |
| `LLM_API_BASE`      | Provider base URL                                         |

Depending on the provider, set `llm_api_protocol` to `chat_completions`
(default), `responses`, or `anthropic_messages` (see the `ApiProtocol` enum).

Sending local files to an external LLM requires a public IP address:
configure `http_external_url`, otherwise the feature is unavailable.


### Configuration

You can also set configuration fields when creating an agent by passing a
`config` dictionary as an argument.

Calling `agent.config_fields_markdown()` prints all configuration fields: type,
description, and default value. Call the method before starting the agent to
see which settings are available with the current set of extensions:

```python
from commamatrix import Agent, agentic_model

async def main() -> None:
    agent = Agent(name="my_lovely_assistant")
    await agent.add_extensions(
        commamatrix.builtin.default_instruction,
        commamatrix.builtin.llm_http_adapter,
        commamatrix.builtin.http_connector,
    )
    print(agent.config_fields_markdown())
```

### Extensions

The extension list is isolated per agent and is not tied to module imports. You
can add your own extensions: CommaMatrix scans the module contents for declared
hooks, tools, instructions, connectors, and other components. Every component
with a lifecycle is automatically added to the agent lifecycle.

By default, everything declared in the `__main__` module and everything inside
`.commamatrix/plugins` is loaded as an extension. Disable this with
`Agent(auto_load_main=False)` and/or `Agent(auto_load_plugins=False)`.

```python
from commamatrix.builtin import data_tools, web_utils
import my_package, my_module

await agent.add_extensions("data_tools", "web_utils")  # names can be used
await agent.add_extensions(my_package.my_extension)
await agent.add_extensions(my_module)
```

Internal package modules must be imported from their `__init__.py`; a re-export
alone is not considered a component declaration.

The main component types are `@tool`, `@instruction`, `@hook` (and the `Hook`
constructor, which lets you create new hook events), `Service`, `Connector`,
`BaseTable`, `Storage`, `FileStorage`, `LLMAdapter`, and
`@lifecycle_component`.

Read the [extension authoring guide](https://github.com/matrixd0t/commamatrix/blob/master/src/commamatrix/builtin/self_extension/guides/main.md).
It also links to the specialized guides.

See the [`examples/`](https://github.com/matrixd0t/commamatrix/tree/master/examples/) directory, which contains an interface agent
and a headless executor that delegates tasks to a subagent.

### Security

- HTTP connector passwords are hashed, and the generated administrator password
  is shown only once on the agent's first launch.
- The default CodeAct backend (`SubprocessBackend`) executes arbitrary Python
  code with access to the standard library, installed dependencies, and the
  terminal. This is **unsafe**. For untrusted users, use an external isolation
  layer such as systemd or Docker.
- Before exposing the HTTP connector, verify your reverse proxy, TLS, CORS, and
  authorization setup.
- Reuse components shared by all extensions instead of creating new ones. For
  example, use `agent.http_client` for Internet requests and
  `agent.http_server` to register your own endpoints.

`written with love by dotmatrix`
