from __future__ import annotations

from dataclasses import dataclass

from openagentpolicy.inventory.schema import Inventory, Tool
from openagentpolicy.policies.schema import ActionType, Condition, Policy, TriggerEvent


@dataclass
class UnresolvedPolicyField:
    policy_id: str
    field: str
    reason: str

    def format(self) -> str:
        return f"Policy {self.policy_id}: field {self.field!r} {self.reason}"


class UnresolvedPolicyFieldsError(ValueError):
    def __init__(self, issues: list[UnresolvedPolicyField]) -> None:
        self.issues = issues
        super().__init__("\n".join(issue.format() for issue in issues))


def validate_policy_fields(
    policies: list[Policy],
    inventory: Inventory,
) -> list[UnresolvedPolicyField]:
    issues: list[UnresolvedPolicyField] = []
    for policy in policies:
        if not policy.enabled or policy.conditions is None or policy.trigger is None:
            continue
        trigger_event = policy.trigger.event
        tool: Tool | None = None
        if policy.trigger.tool_id:
            tool = inventory.get_tool(policy.trigger.tool_id)
        if (
            trigger_event == TriggerEvent.AFTER_TOOL_CALL
            and policy.action is not None
            and policy.action.type
            not in {
                ActionType.WARN,
                ActionType.LOG_ONLY,
                ActionType.REDACT_RESULT,
                ActionType.ESCALATE,
            }
        ):
            issues.append(
                UnresolvedPolicyField(
                    policy_id=policy.id,
                    field="action.type",
                    reason=(
                        "must be one of warn/log_only/redact_result/escalate "
                        "for after_tool_call policies"
                    ),
                )
            )
        issues.extend(
            _validate_condition_tree(
                policy_id=policy.id,
                condition=policy.conditions,
                trigger_event=trigger_event,
                tool=tool,
            )
        )
    return issues


def _validate_condition_tree(
    *,
    policy_id: str,
    condition: Condition,
    trigger_event: TriggerEvent,
    tool: Tool | None,
) -> list[UnresolvedPolicyField]:
    issues: list[UnresolvedPolicyField] = []
    if condition.is_leaf and condition.field:
        issue = _validate_field(
            policy_id=policy_id,
            field=condition.field,
            trigger_event=trigger_event,
            tool=tool,
        )
        if issue is not None:
            issues.append(issue)
    for child in condition.all or []:
        issues.extend(
            _validate_condition_tree(
                policy_id=policy_id,
                condition=child,
                trigger_event=trigger_event,
                tool=tool,
            )
        )
    for child in condition.any or []:
        issues.extend(
            _validate_condition_tree(
                policy_id=policy_id,
                condition=child,
                trigger_event=trigger_event,
                tool=tool,
            )
        )
    if condition.not_ is not None:
        issues.extend(
            _validate_condition_tree(
                policy_id=policy_id,
                condition=condition.not_,
                trigger_event=trigger_event,
                tool=tool,
            )
        )
    return issues


def _validate_field(
    *,
    policy_id: str,
    field: str,
    trigger_event: TriggerEvent,
    tool: Tool | None,
) -> UnresolvedPolicyField | None:
    if field.startswith("metadata.") or field == "agent_id":
        return None
    if field.startswith("tool."):
        if tool is None:
            return UnresolvedPolicyField(
                policy_id=policy_id,
                field=field,
                reason="requires trigger.tool_id to resolve tool metadata fields",
            )
        leaf = field.split(".", 1)[1]
        if leaf not in {"id", "name", "risk_level", "side_effect"}:
            return UnresolvedPolicyField(
                policy_id=policy_id,
                field=field,
                reason="is not a supported tool metadata field",
            )
        return None

    if trigger_event == TriggerEvent.BEFORE_FINAL_RESPONSE:
        if field == "final_response":
            return None
        return UnresolvedPolicyField(
            policy_id=policy_id,
            field=field,
            reason="is not available for before_final_response events",
        )

    if field.startswith("tool_result."):
        if trigger_event == TriggerEvent.AFTER_TOOL_CALL:
            return None
        return UnresolvedPolicyField(
            policy_id=policy_id,
            field=field,
            reason="is only available for after_tool_call events",
        )

    if field.startswith("tool_args."):
        if tool is None:
            return UnresolvedPolicyField(
                policy_id=policy_id,
                field=field,
                reason="requires trigger.tool_id to validate tool arguments",
            )
        arg_name = field.split(".", 1)[1]
        if arg_name not in tool.arguments:
            return UnresolvedPolicyField(
                policy_id=policy_id,
                field=field,
                reason=f"does not exist on tool {tool.id!r}",
            )
        return None

    if "." not in field:
        if trigger_event in {TriggerEvent.BEFORE_TOOL_CALL, TriggerEvent.AFTER_TOOL_CALL}:
            if tool is None:
                return UnresolvedPolicyField(
                    policy_id=policy_id,
                    field=field,
                    reason="requires trigger.tool_id to resolve bare tool argument fields",
                )
            if field not in tool.arguments:
                return UnresolvedPolicyField(
                    policy_id=policy_id,
                    field=field,
                    reason=f"does not exist on tool {tool.id!r}",
                )
            return None
        return UnresolvedPolicyField(
            policy_id=policy_id,
            field=field,
            reason="is not available for this event context",
        )

    return UnresolvedPolicyField(
        policy_id=policy_id,
        field=field,
        reason="is not resolvable from the event context",
    )
