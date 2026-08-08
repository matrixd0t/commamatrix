# Windows installer

This directory contains the current Windows installer for CommaMatrix.

## Current Status

The installer currently provides:

- Windows PowerShell entrypoint;
- automatic installation or reuse of `uv`;
- `uv`-managed Python 3.13;
- a virtual environment in the selected workspace;
- installation of `commamatrix[all]` and desktop runtime dependencies;
- provider and model configuration through an interactive console flow;
- a generated entrypoint, desktop shortcut, optional Startup shortcut, and
  `commamatrix` command on the user `PATH`;
- one-time initialization of the HTTP connector and administrator credentials;
- background execution with a system-tray menu.

The recommended Basic flow uses **OpenCode Zen** with the
`deepseek-v4-flash-free` model. The model is selected by its substring in the
model catalog returned by OpenCode Zen. Reasoning is not an installer option:
every generated entrypoint configures the universal reasoning value `max`.
The runtime maps that value to the highest reasoning mode reported by the
selected model and omits the wire parameter when the model has no reasoning
modes.

## Files

| File                       | Responsibility                                                                                                 |
|----------------------------|----------------------------------------------------------------------------------------------------------------|
| `install.ps1`              | Release PowerShell launcher. Finds or installs `uv`, downloads the bootstrap script, and starts it.            |
| `bootstrap.py`             | Interactive installer, resource loader, environment writer, runtime installer, shortcut creator, and launcher. |
| `manifest.json`            | Release version and names of the wheel and installer resources.                                                |
| `providers.json`           | Provider metadata used by Basic and Advanced mode. It does not contain a model catalog.                        |
| `entrypoint.template.py`   | Template copied into the installed workspace with selected values embedded.                                    |
| `runtime-requirements.txt` | Dependencies for the Windows tray runtime: `pystray` and `Pillow`.                                             |
| `../../assets/`            | Shared release icons: transparent `logo.png` for the tray and `logo.ico` for Windows shortcuts.                |

The installer uses the shared `assets/logo.png` and `assets/logo.ico` files.
They are required installer resources. The runtime still has a generated
fallback icon for manual or damaged installations, but a release install fails
if either asset is missing.

## Release Flow

### 1. User starts PowerShell

The published release asset is `install.ps1`. The script currently contains
the repository, version, and tag as constants:

```powershell
$Repository = "matrixd0t/commamatrix"
$Version = "0.1.10"
$Tag = "v$Version"
```

It builds the raw GitHub URL for `bootstrap.py`, stores that file in the
temporary directory, and runs with `ErrorActionPreference = "Stop"`.

### 2. `uv` is resolved

The script refreshes the machine and user `PATH` and checks for `uv`. If it is
not found, it downloads and executes the official installer from
`https://astral.sh/uv/install.ps1`, refreshes `PATH`, and checks again.

The bootstrap is then started with:

```powershell
uv run --quiet --python 3.13 <temporary-bootstrap.py> `
  --repository <repository> --version <version> --uv <uv-path>
```

The temporary bootstrap file is removed in the `finally` block, including
when installation fails.

### 3. Release resources are downloaded and validated

For a release install, `bootstrap.py` downloads `manifest.json` from the
`v<version>` tag and verifies that `manifest.version` equals the requested
version. It requires safe, single-component file names for the wheel, provider
file, entrypoint template, and runtime requirements; icon paths are restricted
to the repository's `assets/` directory.

The following files are then downloaded:

1. `providers.json`;
2. `entrypoint.template.py`;
3. `runtime-requirements.txt`;
4. `assets/logo.png`;
5. `assets/logo.ico`;
6. the exact wheel named by `manifest.json` from the GitHub release assets.

The release wheel must therefore exist under the exact asset name, for
example `commamatrix-0.1.10-py3-none-any.whl`. The installer does not build a
wheel and does not verify a checksum or signature.

For local development, `bootstrap.py` can use a source tree instead of a
downloaded wheel:

```powershell
uv run --python 3.13 installer/windows/bootstrap.py `
  --source-root . --uv (Get-Command uv).Source
```

The source-tree path still validates `installer/windows/manifest.json`, but it
installs `.[all]` from the source root.

### 4. Language and installation mode

The installer asks for a language first. Empty input selects Russian. English
is also available. All later prompts and provider instructions use the chosen
language.

It then asks for the installation mode:

- **Basic**: fixed workspace, the single provider marked `default`, its
  recommended model, local HTTP binding, and no Windows autostart;
- **Advanced**: workspace, provider or custom provider, protocol, API base,
  token, model, HTTP binding, port, and autostart are configurable.

`providers.json` must contain exactly one default provider for Basic mode. The
committed configuration marks OpenCode Zen as that provider. An empty provider
list, which was the previous state, makes Basic mode fail before installation.

### 5. Provider selection and credentials

The provider descriptor contains:

```json
{
  "id": "opencode-zen",
  "api_base": "https://opencode.ai/zen/v1",
  "token_env": "OPENAI_API_KEY",
  "protocol": "chat_completions",
  "recommended_model": "deepseek-v4-flash-free"
}
```

The release manifest points the icon resources to:

```json
{
  "icon": "assets/logo.png",
  "shortcut_icon": "assets/logo.ico"
}
```

OpenCode Zen exposes an OpenAI-compatible Chat Completions API. The installer
asks for the API key using `getpass`, so the token is not echoed to the
console. It writes the selected API base and token to:

```text
%USERPROFILE%\\commamatrix\\.commamatrix\\.env
```

The `.env` file is overwritten on a subsequent install. It is not encrypted;
protect the workspace and do not commit this file.

Advanced mode also supports a custom provider. Its protocol can be:

- `Chat Completions`;
- `Responses`;
- `Anthropic Messages`.

The model is not selected from a local list. At application initialization,
the LLM HTTP adapter calls the provider's `/v1/models` endpoint, parses the
returned catalog, and filters it using the configured model substring. If no
model contains the configured value, initialization fails with a model-match
error.

### 6. Runtime installation

After selection, the installer creates the workspace, defaulting to:

```text
%USERPROFILE%\\commamatrix
```

It then performs these operations:

1. creates `.commamatrix`;
2. writes `.commamatrix\\.env`;
3. installs the requested Python version through `uv python install 3.13`;
4. finds the managed base Python through `uv python find` and recreates `.venv`
   with `python -m venv --clear --without-pip`;
5. installs `commamatrix[all]` from the release wheel or `.[all]` from the
   source tree;
6. installs `runtime-requirements.txt` into the virtual environment;
7. renders `entrypoint.template.py` into `entrypoint.py`;
8. copies `assets/logo.png` and `assets/logo.ico` into
   `.commamatrix\\assets`;
9. creates `.commamatrix\\bin\\commamatrix.cmd` and adds `.commamatrix\\bin`
   to the user `PATH`.

The generated entrypoint embeds the selected provider values rather than
reading provider selection interactively at runtime. It still reads the token
and API base from `.commamatrix\\.env` on every start.

The generated agent configuration includes:

```python
agentic_model: selected_model,
reasoning_level: "max",
```

There is intentionally no reasoning prompt. This applies equally to Basic,
Advanced, and custom-provider selections.

### 7. Shortcuts and autostart

The installer creates or replaces:

```text
%USERPROFILE%\\Desktop\\CommaMatrix.lnk
%USERPROFILE%\\commamatrix\\.commamatrix\\bin\\commamatrix.cmd
```

If autostart is enabled in Advanced mode, it also creates:

```text
%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\CommaMatrix.lnk
```

The shortcut starts `pythonw.exe` with the generated `entrypoint.py`, using the
workspace as its working directory. The command file uses `start /b` with
`pythonw.exe`, so `commamatrix` launches only the tray process without opening a
new terminal window.

### 8. Initialization and first launch

Before the background process is started, the installer invokes:

```text
.venv\\Scripts\\python.exe entrypoint.py --initialize --credentials-file <temp-file>
```

Initialization loads all extensions listed in the template, starts the agent,
waits for the HTTP connector to create or expose initial administrator
credentials, writes those credentials to a temporary JSON file, and stops the
agent.

The installer reads the temporary credentials, starts the normal runtime with
`pythonw.exe`, deletes the temporary credentials file, and prints the initial
administrator login and password once. Save them immediately. The final
message also confirms the desktop shortcut and tray process.

The Basic HTTP endpoint is local:

```text
http://127.0.0.1:8338/commamatrix
```

If the requested port is already occupied, the generated entrypoint asks the
operating system for an available port. The tray menu opens the actual server
URL, restarts the process, opens the log directory, or closes the application.

## Installed Layout

```text
%USERPROFILE%\\commamatrix\\
  .commamatrix\\
    .env                 # API base and API token
    assets\\
      logo.png           # transparent tray icon
      logo.ico           # Windows shortcut icon
    bin\\
      commamatrix.cmd    # terminal launcher on the user PATH
    logs\\
      commamatrix.log
    ...                  # runtime data, including the default storage
  .venv\\                 # environment created from uv-managed Python
  entrypoint.py           # generated, selected values embedded
```

The workspace data is separate from the virtual environment. Reinstalling
recreates `.venv` and rewrites the generated configuration, but the installer
does not implement migrations, backups, or rollback of existing workspace
data.

## Operations After Installation

- Use the desktop shortcut or `commamatrix` from a new terminal to start the
  application.
- Use the tray menu's **Open CommaMatrix** item to open the web UI.
- Use **Restart** after changing `.env` or `entrypoint.py` manually.
- Use **Open logs** to inspect `%USERPROFILE%\\commamatrix\\.commamatrix\\logs`.
- Run the installer again to replace the environment and configuration. The
  current implementation does not ask for confirmation before overwriting the
  `.env` file or recreating `.venv`.

There is no uninstaller yet. A manual removal must account for the desktop
shortcut, optional Startup shortcut, workspace, and the user `PATH` entry for
`bin`.

## Failure Points and Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `uv was not found after installation` | PowerShell policy, network failure, or `PATH` was not refreshed by the uv installer. |
| Manifest version error | `install.ps1`, the tag, and `manifest.json` versions do not match. |
| Release wheel download fails | The GitHub release is missing the exact wheel asset named in `manifest.json`. |
| Basic mode rejects providers | `providers.json` does not contain exactly one provider with `"default": true`. |
| No LLM model matches the configured value | The provider's model catalog changed, the API key is invalid, or the model is temporarily unavailable. |
| Initialization fails after installation | Inspect `.commamatrix\\logs\\commamatrix.log`; common causes are provider authentication, model discovery, or an unavailable port. |
| Tray process is not visible | Check the generated log and start `entrypoint.py` with `.venv\\Scripts\\python.exe` from a console to see the exception. |

The bootstrap captures subprocess output and reports only the last part of a
failed command. Detailed runtime errors belong in the generated log file.

## Security and Production Gaps

The installer should currently be considered an MVP with these known gaps:

- no Authenticode/MSIX packaging;
- no download checksum, signature, or trusted-release verification;
- no transactional rollback if a later installation step fails;
- no backup or migration strategy for an existing workspace;
- no uninstaller;
- no automated installer test suite in this directory;
- API tokens are stored as plaintext in `.env`;
- Advanced mode can bind the HTTP server to `0.0.0.0`, which exposes it to the
  network and must be protected by the application's authentication and the
  host firewall;
- the template enables the CodeAct extension, which executes arbitrary Python
  and is not a security sandbox;
- the free OpenCode Zen model is subject to the provider's availability,
  quota, and privacy terms. Do not send confidential data unless those terms
  are acceptable.

Before a production installer release, the highest-value improvements are
signed artifact verification, an atomic/rollback-capable install transaction,
workspace backup and migration handling, a proper uninstaller, and automated
tests for release resource loading, provider validation, entrypoint rendering,
and shortcut creation.
