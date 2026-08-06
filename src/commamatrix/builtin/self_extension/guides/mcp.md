# MCP

MCP support is an optional built-in. Install `commamatrix[mcp]` and add
`commamatrix.builtin.mcp` as an extension before using `MCPService`.

```python
await agent.add_extensions("commamatrix.builtin.mcp")
```

## Default Configuration

The built-in JSON loader reads `mcp_config_path`. Its default value is
`.commamatrix/mcp.json`, resolved relative to the current working directory.
An absolute configured path is used as-is. When `MCPService` is initialized,
the loader creates the parent directory and an empty file if they do not exist:

```json
{
  "mcpServers": {}
}
```

The standard file uses the host-style `mcpServers` mapping. The mapping key is
the stable server ID:

```json
{
  "mcpServers": {
    "local-tools": {
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "my_mcp_server"],
      "cwd": ".",
      "env": {
        "MCP_TOKEN": "set-in-the-host-environment"
      },
      "timeout": 30
    },
    "remote-tools": {
      "transport": "streamable_http",
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer set-outside-source-control"
      },
      "timeout": 30
    },
    "legacy-remote": {
      "transport": "sse",
      "url": "https://mcp.example.com/sse"
    }
  }
}
```

Supported transports are `stdio`, `streamable_http`, and `sse`. A `stdio`
server requires `command`; HTTP and SSE servers require `url`. If `transport`
is omitted, a server with `command` defaults to `stdio`, otherwise it defaults
to `streamable_http`. Hyphenated transport names are normalized to underscores.
`timeout` defaults to 30 seconds and must be positive.

Configure the path and MCP client identity per agent when needed:

```python
from commamatrix.builtin.mcp import (
    mcp_client_name,
    mcp_client_version,
    mcp_config_path,
)


agent.config.set(mcp_config_path, ".config/mcp.json")
agent.config.set(mcp_client_name, "my-agent")
agent.config.set(mcp_client_version, "1.0.0")
```

The defaults are `commamatrix` for `mcp_client_name` and `0.1.0` for
`mcp_client_version`. Keep credentials out of source control; the JSON loader
does not expand environment-variable placeholders in strings. Use a protected
file, host configuration, or a custom `MCPConfigLoader` for secret material.

`MCPService` owns configured MCP sessions and mounts discovered remote tools
into the regular `ToolManager`. Remote tools therefore participate in normal
tool discovery, filtering, hooks, and CodeAct exposure.

Access the service from a hook, tool, or service:

```python
from commamatrix.builtin.mcp import MCPService


mcp = ctx.run.agent.services.require(MCPService)
result = await mcp.call_tool(
    "server_id",
    "tool_name",
    {"value": "..."},
)
```

Additional configuration sources must subclass `MCPConfigLoader` and return a
list of `MCPServerSpec` values from `load(agent)`, then be registered with:

```python
await mcp.add_loader(MyMCPConfigLoader())
```

Server IDs must be unique across all loaders. Adding a loader or changing a
loader's data refreshes the MCP server manager and the mounted tool source. A
file change can be applied explicitly with:

```python
mcp = agent.services.require(MCPService)
await mcp.refresh_if_changed()
```

The built-in file loader is one of the registered loaders, so IDs in the JSON
file must not collide with IDs returned by custom loaders.

Treat remote MCP tools as external side effects. Validate server configuration,
credentials, tool permissions, and returned data before exposing them to an
untrusted conversation.

See [builtin/mcp/manager.py](../../mcp/manager.py),
[builtin/mcp/config.py](../../mcp/config.py),
[builtin/mcp/loader.py](../../mcp/loader.py), and
[builtin/mcp/source.py](../../mcp/source.py).



