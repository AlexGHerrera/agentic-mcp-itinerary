from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import List

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


MOCK_CMD = [sys.executable, str(Path(__file__).resolve().parents[2] / "mocks" / "activities_mcp.py")]


def _parse_tool_result(result) -> List[dict]:
    if result.structuredContent is not None:
        structured = result.structuredContent
        if isinstance(structured, list):
            return structured
        if isinstance(structured, dict):
            for key in ("items", "data", "result", "activities"):
                value = structured.get(key)
                if isinstance(value, list):
                    return value
        return []
    if result.content:
        text = " ".join(
            part.text for part in result.content if getattr(part, "text", None)
        ).strip()
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return []
    return []


async def _call_search_tool(tool_name: str, arguments: dict) -> List[dict]:
    server = StdioServerParameters(command=MOCK_CMD[0], args=MOCK_CMD[1:])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return _parse_tool_result(result)


async def search_activities(city: str, date: str, interests: list[str]) -> List[dict]:
    for attempt in range(2):
        try:
            return await _call_search_tool(
                "search_activities",
                {"city": city, "date": date, "interests": interests},
            )
        except Exception:
            if attempt == 1:
                raise
            await asyncio.sleep(0.5)
