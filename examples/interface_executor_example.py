# interface_executor_example.py

"""Run a user-facing interface agent and a headless executor agent.

Required environment variables:

    OPENAI_API_KEY
    LLM_API_BASE
    COMMAMATRIX_INTERFACE_MODEL
    COMMAMATRIX_EXECUTOR_MODEL

The interface agent owns the HTTP connector and the only model-visible
application tool is ``subagent_call_subagent``. The executor has no user
connector; it is started lazily when the interface delegates a request.
"""

from __future__ import annotations

import asyncio
import os

from commamatrix import *  # casual wildcard import is safe


@instruction(priority=1000)
def interface_policy(_ctx: InstructionCtx) -> str:
    """Keep the interface agent focused on delegation and conversation."""
    return """
You are the interface agent. You are the only agent that communicates with the user.

You have no task-execution tools of your own. For every request that requires
research, computation, file work, web access, or any other action, delegate it
to the executor with subagent_call_subagent:

- subagent: "executor"
- tools: "^(?!subagent_).*$"
- continue_from_here: false
- wait_for_result: true
- instructions: include the complete user request and all relevant conversation context

Do not invent the executor result. After it returns, explain the result to the
user in a clear and concise way. For clarification, confirmation, or ordinary
conversation, reply directly without delegating.
"""


def _required_model(env_name: str) -> str:
    value = os.getenv(env_name)
    if not value:
        raise RuntimeError(f"Set {env_name} before starting the example")
    return value


async def main() -> None:
    interface = Agent(
        "interface",
        config={agentic_model: 'deepseek'},  # matches any available deepSeek model
        auto_load_main=False,  # do not add this file contents as agent extension
        auto_load_plugins=False,  # do not add everything in .commamatrix/plugins as agent extensions
    )
    executor = Agent(
        "executor",
        description="Performs delegated research, computation, and tool-based work.",  # optional, convienience-only
        config={agentic_model: 'gpt-5.6-sol'},
        auto_load_main=False,
        auto_load_plugins=True,
    )

    # The interface has transport and delegation only. It never receives the
    # executor's web, data, filesystem, or code-execution extensions.
    await interface.add_extensions(
        builtin.llm_http_adapter,
        builtin.http_connector,
        builtin.subagent,
        __name__,  # loads any addon components from current file
    )

    # The executor is headless. submit_run() adds the internal subagent
    # transport lazily; no HTTP connector is needed here.
    await executor.add_extensions(
        builtin.llm_http_adapter,
        builtin.codeact,
        builtin.web_utils,
        builtin.data_tools,
        builtin.apply_patch,
        builtin.storage_utils,
    )

    await interface.start()
    print(f"Interface is available at {interface.http_server.base_url}")
    try:
        await asyncio.Event().wait()
    finally:
        await interface.stop()
        await executor.stop()


if __name__ == "__main__":
    asyncio.run(main())
