# CommaMatrix Extension Guide

This is the starting point for writing an extension or a third-party integration.

Read this guide first. Then call `self_extension.read_guide` again with the
names of the detailed sections needed for the current task. Read the source
links in those detailed guides when exact behavior, fields, or lifecycle
semantics matter.

## General recommendations

- Prefer the smallest extension point that solves the task.
- Keep reusable extension code in the host project's `.commamatrix/plugins` directory.
- Keep imports declarative and avoid network calls, background tasks, or open resources at import time.
- Keep credentials and deployment-specific values in configuration or environment variables.
- Activate new extensions explicitly for the current agent and reload them after changes.
- Read the relevant detailed guide before implementing unfamiliar framework behavior.

## Detailed guides

- [Tools](tools.md)
- [Hooks](hooks.md)
- [Instructions](instructions.md)
- [Configuration](configuration.md)
- [Services](services.md)
- [Lifecycle](lifecycle.md)
- [Connectors](connectors.md)
- [Tables](tables.md)
- [Providers](providers.md)
- [Dialog](dialog.md)
- [CodeAct](codeact.md)
