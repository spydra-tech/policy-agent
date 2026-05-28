from __future__ import annotations

from typing import Any

from openagentpolicy.inventory.schema import Inventory
from openagentpolicy.policies.schema import Condition, Policy, TriggerEvent


def validate_enforceability(policy: Policy, inventory: Inventory) -> list[str]:
    errors: list[str] = []
    if policy.trigger is None:
        errors.append("missing trigger")
        return errors
    tool = inventory.get_tool(policy.trigger.tool_id or "") if policy.trigger.tool_id else None
    if policy.trigger.tool_id and tool is None:
        errors.append(f"unknown tool_id '{policy.trigger.tool_id}'")
    if policy.conditions is not None:
        errors.extend(
            _validate_condition(policy.conditions, tool, policy.trigger.event)
        )
    return errors


def _validate_condition(
    condition: Condition,
    tool: Any,
    event: TriggerEvent,
) -> list[str]:
    errors: list[str] = []
    if condition.is_leaf and condition.field:
        field = condition.field
        if field.startswith("tool_args."):
            if tool is None:
                errors.append(f"{field} requires trigger.tool_id")
            else:
                arg = field.split(".", 1)[1]
                if arg not in tool.arguments:
                    errors.append(f"{field} not found in tool arguments")
        elif field.startswith("tool_result."):
            if event != TriggerEvent.AFTER_TOOL_CALL:
                errors.append(f"{field} only valid for after_tool_call")
        elif field.startswith("metadata."):
            pass
        elif field in {"final_response", "agent_id", "tool_id"}:
            pass
        elif field.startswith("tool."):
            if field not in {
                "tool.id",
                "tool.name",
                "tool.risk_level",
                "tool.side_effect",
            }:
                errors.append(f"{field} is not supported tool metadata field")
        elif "." not in field:
            if tool is None:
                errors.append(f"{field} requires trigger.tool_id")
            elif field not in tool.arguments:
                errors.append(f"{field} not found in tool arguments")
        else:
            errors.append(f"{field} is not resolvable")
    for child in condition.all or []:
        errors.extend(_validate_condition(child, tool, event))
    for child in condition.any or []:
        errors.extend(_validate_condition(child, tool, event))
    if condition.not_ is not None:
        errors.extend(_validate_condition(condition.not_, tool, event))
    return errors
