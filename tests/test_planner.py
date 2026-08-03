# tests/test_planner.py

from __future__ import annotations

import sys
import types

import pytest

from commamatrix.builtin.planner import (
    PythonScheduledTaskSource,
    ScheduledTaskContext,
    every,
    task,
)
from commamatrix.builtin.planner.decorators import TASK_ATTRIBUTE


def test_scheduled_task_context_requires_task_id():
    with pytest.raises(TypeError):
        ScheduledTaskContext(agent=object())

    context = ScheduledTaskContext(agent=object(), task_id="module:task")
    assert context.task_id == "module:task"


def test_scheduled_task_source_restores_live_state_after_scan_error():
    module_name = "planner_scan_rollback_test"
    module = types.ModuleType(module_name)

    @task(every(60))
    async def valid_task():
        pass

    valid_task.__module__ = module_name
    module.valid_task = valid_task
    sys.modules[module_name] = module

    try:
        source = PythonScheduledTaskSource()
        source.set_scope([module_name])
        descriptors = source.scan()
        descriptor = descriptors[0]
        previous_functions = dict(source._functions)
        previous_options = dict(source._options)

        def invalid_task():
            pass

        invalid_task.__module__ = module_name
        setattr(invalid_task, TASK_ATTRIBUTE, {})
        module.invalid_task = invalid_task

        with pytest.raises(KeyError):
            source.scan()

        assert source._functions == previous_functions
        assert source._options == previous_options
        assert source._functions[descriptor.id] is valid_task
    finally:
        del sys.modules[module_name]
