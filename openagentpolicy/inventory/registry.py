from __future__ import annotations

from typing import Any, Callable

from openagentpolicy.inventory.schema import Tool

POLICY_TOOL_ATTR = "_openagentpolicy_tool"


def get_tool_definition(func: Callable[..., Any]) -> Tool | None:
    return getattr(func, POLICY_TOOL_ATTR, None)
