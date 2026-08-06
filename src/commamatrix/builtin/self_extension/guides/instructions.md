# Instructions

An instruction is a top-level function decorated with `@instruction`. It
returns a fragment of the system prompt for the current LLM call.

```python
from datetime import datetime, timezone

from commamatrix import InstructionCtx, instruction


@instruction(priority=10)
def current_time(_ctx: InstructionCtx) -> str:
    """Give the model the current UTC time."""
    now = datetime.now(timezone.utc)
    return f"Current UTC time: {now:%Y-%m-%d %H:%M}"
```

The handler receives `InstructionCtx` and returns `str | None`. Returning
`None` omits the fragment. Instructions may be synchronous or asynchronous;
use async code for I/O.

Before each normal LLM call, non-`None` fragments are stripped, joined with
blank lines, and inserted at the beginning of the in-memory dialog as a
`SYSTEM` item. This item is not persisted as ordinary conversation history.
The built-in instruction aggregator skips this step for headless subagent runs.

## Ordering

Instructions support `priority`, `before`, and `after`, with the same ordering
rules as hooks: constraints take precedence, then higher priority runs first,
then declaration order breaks ties.

```python
@instruction(after=current_time)
async def user_rules(ctx: InstructionCtx) -> str | None:
    rules = ctx.run.state.get("rules")
    return "\n".join(rules) if rules else None
```

Use an instruction for reusable behavior, response style, or dynamic context.
Do not use it for a temporary fact that should apply only to the current input;
put that fact in run state or dialog input instead.

See [components/instruction.py](../../../components/instruction.py).

