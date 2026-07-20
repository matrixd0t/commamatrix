# Tests

The project uses `pytest` with the test suite rooted at this directory. The
repository uses a `src/` layout, so `pyproject.toml` adds `src` to pytest's
Python path.

## Running Tests

Install the test dependencies with:

```text
python -m pip install -e ".[test]"
```

Run the complete suite:

```text
python -m pytest
```

Run only CodeAct tests:

```text
python -m pytest tests/test_codeact.py -q
```

Run a focused group by keyword:

```text
python -m pytest -k codeact
```

Inspect test collection without running tests:

```text
python -m pytest --collect-only
```

## Layout

- `test_codeact.py` covers the CodeAct RPC protocol, authenticated TCP
  transport, standalone worker process, and `SubprocessBackend` lifecycle.
- Additional component tests should use `test_<component>.py` names and live
  directly under `tests/` or in a component-specific subdirectory.
- Shared fixtures belong in `conftest.py` at the narrowest directory that
  needs them.

## CodeAct Test Scope

The CodeAct tests intentionally exercise real child processes and real
loopback TCP connections. They verify:

- token handshake and NDJSON framing;
- worker execution and top-level `await`;
- nested tool RPC calls;
- Python failures, execution timeout, cancellation, and cleanup;
- output truncation by UTF-8 byte size.

The worker is launched as a standalone script. Tests must not make the worker
import `commamatrix`; only the parent-side test process imports framework
modules.

The TCP endpoint is always bound to `127.0.0.1` and uses a per-test random
token. The transport is used instead of subprocess stdin/stdout because it is
reliable with asyncio on Windows and matches the transport planned for Docker
and Systemd execution backends.
