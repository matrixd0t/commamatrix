# builtin/tools/example_tools.py

import asyncio
from commamatrix.components.tool import tool


@tool(alias='')
async def echo(expression: str) -> str:
    """Test tool. echoes expression twice"""
    return f'{expression}\n{expression}'

