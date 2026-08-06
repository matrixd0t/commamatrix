# Security

Extensions can add network access, filesystem access, database writes, external
messages, code execution, and background tasks. Treat every such extension as
application code with the agent's process privileges.

## Secrets

Keep credentials in host configuration or environment variables through
`ConfigField`. Do not include them in source code, tool descriptions, metadata,
logs, dialog content, or error messages.

## HTTP Exposure

The default HTTP bind host is `0.0.0.0`, which exposes the server beyond the
local machine. For development configure `http_host` as `127.0.0.1`. For public
deployment configure TLS, authentication, reverse-proxy headers, CORS, rate
limits, and network access deliberately.

The built-in HTTP authentication hashes passwords and uses JWT tokens, but
deployment still owns transport security and access policy.

## Files and URLs

Use `resolve_path()` and the configured `allow_absolute_paths` policy for user
paths. Do not construct file paths by string concatenation. File IDs must not be
treated as arbitrary paths.

Web-facing tools must preserve URL validation, credential rejection, redirect
validation, and private-host protections. SSRF checks are a security boundary,
not an optional convenience.

## Code Execution

CodeAct's subprocess backend is intentionally NOT a security sandbox. Generated code can access the
process environment, installed packages, filesystem, and terminal. Do not
expose it to untrusted users without an external isolation boundary and a strict
tool authorization policy.

## Extension Lifecycle

Do not perform irreversible work at import time. Validate authorization before
external side effects. Make listeners, clients, child processes, and tasks
owned by a service or lifecycle component and stop them during `stop()`.

When reloading an extension, ensure the replacement cannot retain resources from
the previous module. Keep cleanup paths idempotent and avoid silently replacing
missing security-sensitive dependencies with fake fallbacks.

See [utils.py](../../../utils.py),
[builtin/web_utils/security.py](../../web_utils/security.py),
[components/server.py](../../../components/server.py), and
[builtin/codeact/service.py](../../codeact/service.py).

