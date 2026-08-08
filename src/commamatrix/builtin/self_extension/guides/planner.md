# Scheduled Tasks

The planner is an optional built-in backed by `matrix-planner`. It discovers
function declarations in the active extension scope and runs them on an
in-memory schedule owned by the current agent. It does not persist schedules or
execution history.

Install the optional dependency and activate the built-in explicitly:

```shell
uv add "commamatrix[planner]"
```

```python
await agent.add_extensions("commamatrix.builtin.planner")
```

The module that contains a task must also be active. It can be loaded from the
workspace plugin directory, or activated explicitly:

```python
await agent.add_extensions(
    "commamatrix.builtin.planner",
    "my_project.automation",
)
```

## Declare a Task

Use `@task` on a public top-level function in an active extension module. The
decorator requires one `matrix_planner.Schedule` object:

```python
# my_project/automation.py
from datetime import timezone

from commamatrix.builtin.planner import ScheduledTaskContext, cron, task


@task(cron("0 12 * * 1", tz=timezone.utc))
async def weekly_digest(ctx: ScheduledTaskContext) -> None:
    print(f"Running {ctx.task_id} at {ctx.scheduled_at.isoformat()}")
```

Tasks may be synchronous or asynchronous. Synchronous functions are executed
in a worker thread so they do not block the agent event loop. If a synchronous
function returns an awaitable, the awaitable is awaited as well. The task's
return value is not delivered to a connector or stored as dialog history.

Discovery follows the normal Python source rules:

- The function must be declared at module level in a module active for this
  agent.
- Private names and cross-module re-exports are ignored.
- A package must import a nested module from its `__init__.py` before the nested
  declarations can be discovered.

See [main.md](main.md) for the complete extension discovery model.

## Schedules

Create a new schedule expression for each task. Schedule objects are stateful
iterators; sharing one object between multiple task declarations makes them
consume the same schedule state.

### Cron

`cron(expression, *, tz=None)` creates a wall-clock schedule from the cron
expression accepted by `matrix-planner`:

```python
@task(cron("*/15 * * * *", tz=timezone.utc))
async def quarter_hour_check() -> None: ...
```

The optional `tz` controls the timezone used to calculate matching times. A
cron schedule asks for the next matching time when its runner starts; it does
not replay times missed while the agent was stopped.

### Intervals

`every(value, *, anchor="start")` creates a monotonic interval schedule. The
value may be a positive number of seconds, a `timedelta`, or a string using
`s`, `m`, `h`, or `d` units:

```python
from datetime import timedelta

from commamatrix.builtin.planner import every, task


@task(every("10m"))
async def refresh_cache() -> None: ...


@task(every(timedelta(hours=1), anchor="end"))
def compact_cache() -> None: ...
```

With the default `anchor="start"`, ticks follow a fixed cadence based on the
time at which the schedule was created. With `anchor="end"`, the next interval
starts after the previous execution finishes. A positive numeric value is
interpreted as seconds; invalid or non-positive intervals raise an exception
when the schedule is created.

### One-Time Tasks

`once(at)` fires exactly once at the supplied `datetime`:

```python
from datetime import datetime, timezone

from commamatrix.builtin.planner import once, task


@task(once(datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)))
async def year_end_cleanup() -> None: ...
```

The schedule is in memory. A `once` task whose time is already in the past is
due immediately after the scheduler starts, but a completed task is not
recorded for a future process. If the extension is removed and later added
again, its declaration creates a new schedule.

## Task Options

`@task(schedule, **options)` accepts these options:

| Option        | Meaning                                                                       |
|---------------|-------------------------------------------------------------------------------|
| `name`        | Human-readable scheduler name. It does not change task identity.              |
| `args`        | Positional arguments passed on every invocation.                              |
| `kwargs`      | Keyword arguments passed on every invocation.                                 |
| `max_retries` | Number of retries after the initial failed attempt. Defaults to `0`.          |
| `backoff`     | Delay in seconds between retries, or a callable receiving the attempt number. |
| `on_error`    | Synchronous or asynchronous callback receiving the exception.                 |
| `timeout`     | Per-execution timeout as seconds, a `timedelta`, or a duration string.        |

For example:

```python
async def report_task_error(error: Exception) -> None:
    print(f"Scheduled task failed: {error}")


@task(
    every("5m"),
    name="refresh-reports",
    max_retries=2,
    backoff=lambda attempt: min(60, 2**attempt),
    timeout="2m",
    on_error=report_task_error,
)
async def refresh_reports() -> None: ...
```

The scheduler keeps the task registered after an execution fails. Without an
`on_error` callback, failures are logged by `matrix-planner`. With a callback,
it is called for each failed retry attempt. A timeout calls `on_error` when one
is configured and ends that execution; it does not start another retry for the
timeout. If an error callback itself fails, that callback failure belongs to
the scheduler runner.

The `args` and `kwargs` options are useful when the same function is intended
to be called with fixed values. They are part of the task fingerprint, so
changing them replaces the registered task during refresh.

## Runtime Context

If the function signature contains a parameter named exactly `ctx`, and
`kwargs` does not already provide it, CommaMatrix injects a
`ScheduledTaskContext`:

```python
from commamatrix.builtin.planner import ScheduledTaskContext, every, task


@task(every("1h"))
async def hourly_job(ctx: ScheduledTaskContext) -> None:
    agent = ctx.agent
    task_id = ctx.task_id
    scheduled_at = ctx.scheduled_at
    ...
```

The context contains:

- `agent`: the owning `Agent` instance.
- `task_id`: the stable identifier `<module>:<function>`.
- `scheduled_at`: the UTC time at which the invocation context was created.

Injection is based on the parameter name, not on the annotation. Do not also
pass `ctx` through `args` or `kwargs` unless the task deliberately wants to
provide its own value.

A scheduled task can submit an agent run. Use a persisted `parent_item_id`
when the task is meant to continue an existing branch rather than start an
unrelated conversation:

```python
@task(every("1h"))
async def continue_report(ctx: ScheduledTaskContext) -> None:
    await ctx.agent.submit_run(
        parent_item_id=report_item_id,
        instructions="Update the report using the latest available data.",
        tools="reports_.*",
        wait_for_result=False,
    )
```

`Agent.submit_run()` is provided by the [headless subagent built-in](subagent.md)
and activates its internal transport on demand. The target agent must still
have an LLM adapter and all extensions required by the submitted run.

## Refresh and Lifecycle

One `AgentScheduler` is created for each agent that activates the planner
built-in. It owns one `matrix_planner.Planner` and reconciles it with all
discovered `@task` declarations.

The identity of a declaration is `<module>:<function>`. The scheduler
fingerprints its schedule and task options:

- A new declaration is registered.
- A removed declaration is unregistered and its runner is cancelled.
- A changed schedule or option removes the old task and registers the new one.
- An unchanged declaration keeps its existing scheduler registration.

These changes are applied during startup and extension refresh operations:

```python
await agent.refresh_extensions()
await agent.reload_extensions("my_project.automation")
await agent.remove_extensions("my_project.automation")
```

Removing a task or stopping the agent does not undo data or side effects that
the task already created. Shutdown cancels active scheduler runners, so task
code should handle cancellation and release its own temporary resources when
necessary. Keep network clients and other long-lived resources in a
`Service`, not in module-level task state.

The scheduler does not persist task definitions, completed runs, or missed
executions. Put declarations in a persistent extension module when they should
return after an agent restart, and use application storage when a task needs
durable state or idempotency.

See [builtin/planner/decorators.py](../../planner/decorators.py),
[builtin/planner/service.py](../../planner/service.py),
[core/agent/agent.py](../../../core/agent/agent.py), and
[runtime.md](runtime.md).
