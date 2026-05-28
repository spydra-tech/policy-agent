from __future__ import annotations

from typing import Any

from openagentpolicy.policies.schema import Condition, ConditionOperator, Policy


def generate_test_cases(policy: Policy) -> list[dict[str, Any]]:
    if policy.trigger is None or policy.conditions is None:
        return []
    leaves = _collect_leaves(policy.conditions)
    base_args: dict[str, Any] = {}
    block_args: dict[str, Any] = {}
    for leaf in leaves:
        if leaf.field is None or leaf.operator is None:
            continue
        key = leaf.field.removeprefix("tool_args.")
        if leaf.operator == ConditionOperator.GT and isinstance(leaf.value, (int, float)):
            block_args[key] = leaf.value + 1
            base_args.setdefault(key, leaf.value - 1)
        elif leaf.operator == ConditionOperator.LT and isinstance(leaf.value, (int, float)):
            block_args[key] = leaf.value - 1
            base_args.setdefault(key, leaf.value + 1)
        elif leaf.operator == ConditionOperator.EQ:
            block_args[key] = leaf.value
            if isinstance(leaf.value, str):
                base_args.setdefault(key, f"not_{leaf.value}")
            elif isinstance(leaf.value, bool):
                base_args.setdefault(key, not leaf.value)
    trigger_event = policy.trigger.event.value
    tool_id = policy.trigger.tool_id or ""
    cases = [
        {
            "name": "Expected block case",
            "event": {
                "event_type": trigger_event,
                "tool_id": tool_id,
                "tool_args": block_args,
            },
            "expected_decision": "block",
        }
    ]
    if base_args:
        cases.append(
            {
                "name": "Expected allow baseline case",
                "event": {
                    "event_type": trigger_event,
                    "tool_id": tool_id,
                    "tool_args": base_args,
                },
                "expected_decision": "allow",
            }
        )
    return cases


def _collect_leaves(condition: Condition) -> list[Condition]:
    leaves: list[Condition] = []
    if condition.is_leaf:
        leaves.append(condition)
    for child in condition.all or []:
        leaves.extend(_collect_leaves(child))
    for child in condition.any or []:
        leaves.extend(_collect_leaves(child))
    if condition.not_ is not None:
        leaves.extend(_collect_leaves(condition.not_))
    return leaves
