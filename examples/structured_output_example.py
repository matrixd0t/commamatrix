# examples/structured_output_example.py
"""Classify text with a headless agent."""

from __future__ import annotations

import asyncio
import os
from typing import Literal

from pydantic import BaseModel

from commamatrix import Agent, agentic_model
from commamatrix.builtin import llm_http_adapter


class TextClassification(BaseModel):
    category: Literal["question", "request", "feedback", "other"]
    summary: str


async def main() -> None:
    agent = Agent(
        "text-classifier",
        config={agentic_model: os.getenv("COMMAMATRIX_MODEL") or ''},
        auto_load_main=False,
        auto_load_plugins=False,
    )
    await agent.add_extensions(llm_http_adapter)

    # submit_run() starts the agent lazily; no start/stop loop is needed here.
    result = await agent.submit_run(
        instructions="""
Classify the following text and return a short summary:

"Can you move tomorrow's meeting to Friday afternoon?"
""",
        tools="",
        response_format=TextClassification,
    )
    if result is None or result.structured_output is None:
        raise RuntimeError("The classifier did not return a structured result")

    print(result.structured_output.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
