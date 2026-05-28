from __future__ import annotations

from typing import Any, Callable

from openagentpolicy.inventory.schema import Tool

POLICY_TOOL_ATTR = "_openagentpolicy_tool"
_REGISTERED_TOOLS: dict[str, Tool] = {}


def get_tool_definition(func: Callable[..., Any]) -> Tool | None:
    return getattr(func, POLICY_TOOL_ATTR, None)


def register_tool_definition(tool: Tool) -> None:
    _REGISTERED_TOOLS[tool.id] = tool


def registered_tools() -> list[Tool]:
    return list(_REGISTERED_TOOLS.values())


def clear_registered_tools() -> None:
    _REGISTERED_TOOLS.clear()
