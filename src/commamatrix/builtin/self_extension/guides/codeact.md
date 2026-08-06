# CodeAct

CodeAct is an optional extension for executing generated Python code and
calling registered tools through a worker gateway. Activate the extension only
when the host has installed its optional dependency and accepts its trust model.

```python
await agent.add_extensions("commamatrix.builtin.codeact")
```

The extension provides tools such as `execute`, `tool_search`, and
`tools_list`. Generated code can use virtual modules for registered tools.

## Tool Names

For a grouped tool:

```python
@tool(alias="fs")
async def read_file(path: str) -> str:
    ...
```

the normal generated import is conceptually:

```python
import tools.fs as fs

content = await fs.read_file(path="README.md")
```

Use an explicit stable alias for tools intended for CodeAct. The tool manager
also exposes name-based virtual namespaces for generated code, but extension
code should use `run.tools` rather than depending on the source filename.

The public LLM-facing name is still `fs_read_file`; CodeAct's import path and
the LLM public name are different concepts. `@tool(alias="")` exposes a bare
function name.

Nested CodeAct tool calls go through the agent's normal before-tool and
after-tool hooks. They can return raw Python values to the worker without
creating an extra persisted tool-result item.

## Trust Boundary

The default `SubprocessBackend` is not a security sandbox. Executed code can
access the standard library, installed dependencies, the filesystem allowed to
the process, and the system terminal. A separate process does not make
untrusted execution safe.

Do not expose CodeAct to untrusted users without an external isolation and
authorization boundary. Preserve execution, RPC, shutdown, and output limits.
Configure the backend and timeouts through the CodeAct `ConfigField` values.

Custom execution backends implement async `start()`, `stop()`, and
`execute(code, ctx)` methods. Treat backend selection as a deployment security
decision, not only a performance setting.

See [builtin/codeact/service.py](../../codeact/service.py),
[builtin/codeact/tools.py](../../codeact/tools.py),
[builtin/codeact/executor/backend.py](../../codeact/executor/backend.py), and
[components/tool.py](../../../components/tool.py).

