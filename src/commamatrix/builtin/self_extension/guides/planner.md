# Scheduled Tasks

The planner is an optional built-in backed by `matrix-planner`. Activate
`commamatrix.builtin.planner` after installing the corresponding optional
dependency.

Declare tasks as top-level functions in an active extension module:

```python
from commamatrix.builtin.planner import ScheduledTaskContext, cron, task


@task(cron("0 12 * * 1"))
async def weekly_digest(ctx: ScheduledTaskContext) -> None:
    print(ctx.task_id)
```

Use `cron(...)`, `every(...)`, or `once(...)` schedules exposed by the built-in
planner. A function named `ctx` receives `ScheduledTaskContext` automatically.
Tasks may also be synchronous; the planner runs synchronous task functions in a
worker thread.

The task identity is `<module>:<function>`. Keep function names unique within a
module. Schedule and task options are fingerprinted, so extension refresh
reconciles added, removed, and changed tasks.

Keep task declarations in persistent extension modules when they should return
after an agent restart. Removing the extension removes the scheduled task, but
does not delete application data created by the task.

When a task should continue an existing conversation branch, use the agent API
with `parent_item_id`:

```python
await ctx.agent.submit_run(
    parent_item_id=item_id,
    tools="reports_.*",
)
```

Do not create a new unrelated dialog history when the task is meant to continue
the stored branch. Use the planner's own documentation for exact schedule
semantics and missed-run behavior.

See [builtin/planner/decorators.py](../../planner/decorators.py),
[builtin/planner/service.py](../../planner/service.py), and
[core/agent/agent.py](../../../core/agent/agent.py).

