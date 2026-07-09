from ..api import tool


@tool
async def calculator(expression: str) -> str:
    """Evaluate a mathematical expression."""
    try:
        result = eval(expression)
        return result
    except Exception as e:
        return f"Error: {e}"


@tool(role="admin")
async def web_search(query: str = "what is the weather in SF today?") -> str:
    """Web search on query."""
    await asyncio.sleep(0.5)
    return "San Francisco will be mostly cloudy today with some afternoon sun, reaching about 67 °F (20 °C)."
