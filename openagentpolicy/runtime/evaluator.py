from __future__ import annotations

import re
from typing import Any

from openagentpolicy.policies.schema import (
    ActionType,
    Condition,
    ConditionOperator,
    Policy,
    PolicyAction,
    TriggerEvent,
)
from openagentpolicy.runtime.decisions import DecisionType, PolicyDecision

# Most restrictive first (lower rank = stricter).
DECISION_PRECEDENCE: tuple[DecisionType, ...] = (
    DecisionType.BLOCK,
    DecisionType.MODIFY_ARGS,
    DecisionType.WARN,
    DecisionType.ESCALATE,
    DecisionType.REDACT_RESULT,
    DecisionType.LOG_ONLY,
    DecisionType.ALLOW,
)


def _decision_rank(decision: DecisionType) -> int:
    return DECISION_PRECEDENCE.index(decision)


class PolicyEvaluator:
    """Deterministic policy evaluator for structured policies."""

    def evaluate(
        self,
        tool_id: str,
        context: dict[str, Any],
        policies: list[Policy],
        *,
        trigger_event: TriggerEvent | None = None,
        agent_id: str | None = None,
        default_decision: DecisionType = DecisionType.ALLOW,
    ) -> PolicyDecision:
        matches: list[tuple[Policy, PolicyDecision]] = []

        for policy in policies:
            if not policy.enabled:
                continue
            if not self._policy_matches(
                policy, tool_id, trigger_event, agent_id=agent_id
            ):
                continue
            if policy.conditions and not self._evaluate_condition(
                policy.conditions, context
            ):
                continue
            if policy.action is None:
                continue
            matches.append((policy, self._decision_from_action(policy)))

        if not matches:
            return PolicyDecision(
                decision=default_decision,
                message="No matching policy; default allow",
            )

        strictest_rank = min(_decision_rank(d.decision) for _, d in matches)
        winners = [
            (policy, decision)
            for policy, decision in matches
            if _decision_rank(decision.decision) == strictest_rank
        ]
        merged = self._merge_decisions(winners)
        return merged.model_copy(
            update={"matched_policies": [policy.id for policy, _ in matches]}
        )

    def _policy_matches(
        self,
        policy: Policy,
        tool_id: str,
        trigger_event: TriggerEvent | None,
        *,
        agent_id: str | None = None,
    ) -> bool:
        if policy.trigger is None:
            return False
        if trigger_event is None or policy.trigger.event != trigger_event:
            return False
        if policy.trigger.tool_id and policy.trigger.tool_id != tool_id:
            return False
        if policy.trigger.agent_id is not None:
            if agent_id is None or policy.trigger.agent_id != agent_id:
                return False
        return True

    def _decision_from_action(self, policy: Policy) -> PolicyDecision:
        assert policy.action is not None
        action = policy.action
        return PolicyDecision(
            decision=action.type,
            matched_policies=[policy.id],
            message=action.message,
            modified_args=action.set,
        )

    def _merge_decisions(
        self, winners: list[tuple[Policy, PolicyDecision]]
    ) -> PolicyDecision:
        policy, decision = winners[0]
        merged_args: dict[str, object] | None = None
        if decision.modified_args:
            merged_args = dict(decision.modified_args)

        for other_policy, other in winners[1:]:
            if other.modified_args:
                merged_args = {**(merged_args or {}), **other.modified_args}

        return PolicyDecision(
            decision=decision.decision,
            matched_policies=[p.id for p, _ in winners],
            message=decision.message
            or next((d.message for _, d in winners if d.message), None),
            modified_args=merged_args,
        )

    def _evaluate_condition(self, condition: Condition, ctx: dict[str, Any]) -> bool:
        if condition.is_leaf:
            return self._evaluate_leaf(condition, ctx)
        if condition.all is not None:
            return all(
                self._evaluate_condition(c, ctx) for c in condition.all
            )
        if condition.any is not None:
            return any(
                self._evaluate_condition(c, ctx) for c in condition.any
            )
        if condition.not_ is not None:
            return not self._evaluate_condition(condition.not_, ctx)
        return True

    def _evaluate_leaf(self, condition: Condition, ctx: dict[str, Any]) -> bool:
        assert condition.field is not None
        assert condition.operator is not None
        actual = resolve_field(ctx, condition.field)
        op = condition.operator
        expected = condition.value

        if op == ConditionOperator.EXISTS:
            return actual is not None
        if op == ConditionOperator.NOT_EXISTS:
            return actual is None
        if op == ConditionOperator.IN:
            return actual in (expected or [])
        if op == ConditionOperator.NOT_IN:
            return actual not in (expected or [])
        if op == ConditionOperator.CONTAINS:
            if actual is None:
                return False
            if isinstance(actual, str) and isinstance(expected, str):
                if condition.case_sensitive:
                    return expected in actual
                return expected.lower() in actual.lower()
            return expected in actual
        if op == ConditionOperator.REGEX:
            if not isinstance(actual, str) or not isinstance(expected, str):
                return False
            flags = 0 if condition.case_sensitive else re.IGNORECASE
            try:
                return re.search(expected, actual, flags=flags) is not None
            except re.error:
                return False
        if op == ConditionOperator.EQ:
            return actual == expected
        if op == ConditionOperator.NE:
            return actual != expected
        if op == ConditionOperator.GT:
            return actual is not None and expected is not None and actual > expected
        if op == ConditionOperator.GTE:
            return actual is not None and expected is not None and actual >= expected
        if op == ConditionOperator.LT:
            return actual is not None and expected is not None and actual < expected
        if op == ConditionOperator.LTE:
            return actual is not None and expected is not None and actual <= expected
        return False


def resolve_field(context: dict[str, Any], field: str) -> Any:
    """Resolve dotted field paths against the evaluation context."""
    value = _walk_path(context, field.split("."))
    if value is None and "." not in field:
        value = _walk_path(context, ["tool_args", field])
    return value


def _walk_path(value: Any, parts: list[str]) -> Any:
    for part in parts:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def build_evaluation_context(
    *,
    tool_args: dict[str, Any] | None = None,
    tool_result: dict[str, Any] | None = None,
    tool: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    final_response: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Build the standard evaluator context from event fields."""
    return {
        "tool_args": tool_args or {},
        "tool_result": tool_result,
        "tool": tool or {},
        "metadata": metadata or {},
        "final_response": final_response,
        "agent_id": agent_id,
    }
