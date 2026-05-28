from openagentpolicy.policies.schema import (
    ActionType,
    Condition,
    ConditionOperator,
    Policy,
    PolicyAction,
    PolicyTrigger,
    TriggerEvent,
)
from openagentpolicy.runtime.decisions import DecisionType
from openagentpolicy.runtime.evaluator import (
    PolicyEvaluator,
    build_evaluation_context,
    resolve_field,
)


def _ctx(**kwargs: object) -> dict:
    return build_evaluation_context(
        tool_args=kwargs.get("tool_args") or {},  # type: ignore[arg-type]
        tool_result=kwargs.get("tool_result"),  # type: ignore[arg-type]
        tool=kwargs.get("tool"),  # type: ignore[arg-type]
        metadata=kwargs.get("metadata"),  # type: ignore[arg-type]
        final_response=kwargs.get("final_response"),  # type: ignore[arg-type]
        agent_id=kwargs.get("agent_id"),  # type: ignore[arg-type]
    )


def _policy(
    policy_id: str,
    *,
    conditions: Condition | None,
    action_type: ActionType = ActionType.BLOCK,
    tool_id: str = "approve_loan",
    event: TriggerEvent = TriggerEvent.BEFORE_TOOL_CALL,
    enabled: bool = True,
) -> Policy:
    return Policy(
        id=policy_id,
        enabled=enabled,
        trigger=PolicyTrigger(event=event, tool_id=tool_id),
        conditions=conditions,
        action=PolicyAction(type=action_type, message=f"matched {policy_id}"),
    )


def test_approved_amount_gt_5000_blocks() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        _policy(
            "block-large",
            conditions=Condition(
                field="tool_args.approved_amount",
                operator=ConditionOperator.GT,
                value=5000,
            ),
        )
    ]
    result = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={"approved_amount": 7500, "approval_mode": "manual"}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    assert result.decision == DecisionType.BLOCK
    assert "block-large" in result.matched_policies


def test_approval_mode_eq_auto_blocks() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        _policy(
            "block-auto",
            conditions=Condition(
                field="tool_args.approval_mode",
                operator=ConditionOperator.EQ,
                value="auto",
            ),
        )
    ]
    result = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={"approved_amount": 100, "approval_mode": "auto"}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    assert result.decision == DecisionType.BLOCK
    assert "block-auto" in result.matched_policies


def test_no_match_allows() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        _policy(
            "block-large",
            conditions=Condition(
                field="tool_args.approved_amount",
                operator=ConditionOperator.GT,
                value=5000,
            ),
        )
    ]
    result = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={"approved_amount": 1000, "approval_mode": "manual"}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    assert result.decision == DecisionType.ALLOW
    assert result.matched_policies == []


def test_exists_and_not_exists() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        _policy(
            "require-trace",
            conditions=Condition(
                field="metadata.trace_id",
                operator=ConditionOperator.EXISTS,
            ),
        )
    ]
    missing = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={"approved_amount": 1}, metadata={}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    present = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={"approved_amount": 1}, metadata={"trace_id": "t-1"}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    assert missing.decision == DecisionType.ALLOW

    policies_not_exists = [
        _policy(
            "deny-trace",
            conditions=Condition(
                field="metadata.trace_id",
                operator=ConditionOperator.NOT_EXISTS,
            ),
        )
    ]
    blocked = evaluator.evaluate(
        "approve_loan",
        _ctx(metadata={}),
        policies_not_exists,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    assert present.decision == DecisionType.BLOCK
    assert blocked.decision == DecisionType.BLOCK


def test_in_and_not_in() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        _policy(
            "block-modes",
            conditions=Condition(
                field="tool_args.approval_mode",
                operator=ConditionOperator.IN,
                value=["auto", "express"],
            ),
        )
    ]
    blocked = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={"approval_mode": "express"}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    allowed = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={"approval_mode": "manual"}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    assert blocked.decision == DecisionType.BLOCK
    assert allowed.decision == DecisionType.ALLOW

    policies_not_in = [
        _policy(
            "block-manual-only",
            conditions=Condition(
                field="tool_args.approval_mode",
                operator=ConditionOperator.NOT_IN,
                value=["manual", "review"],
            ),
        )
    ]
    blocked_not_in = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={"approval_mode": "auto"}),
        policies_not_in,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    assert blocked_not_in.decision == DecisionType.BLOCK


def test_multiple_policies_choose_block_over_warn() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        _policy(
            "warn-large",
            conditions=Condition(
                field="tool_args.approved_amount",
                operator=ConditionOperator.GT,
                value=1000,
            ),
            action_type=ActionType.WARN,
        ),
        _policy(
            "block-large",
            conditions=Condition(
                field="tool_args.approved_amount",
                operator=ConditionOperator.GT,
                value=5000,
            ),
            action_type=ActionType.BLOCK,
        ),
    ]
    result = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={"approved_amount": 9000}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    assert result.decision == DecisionType.BLOCK
    assert set(result.matched_policies) == {"warn-large", "block-large"}


def test_resolve_nested_tool_result_path() -> None:
    context = _ctx(
        tool_args={"approved_amount": 100},
        tool_result={"status": "approved", "details": {"code": 200}},
    )
    assert resolve_field(context, "tool_result.status") == "approved"
    assert resolve_field(context, "tool_result.details.code") == 200
    assert resolve_field(context, "tool_args.approved_amount") == 100


def test_skips_disabled_and_wrong_event() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        _policy(
            "disabled",
            conditions=Condition(
                field="tool_args.approved_amount",
                operator=ConditionOperator.GT,
                value=0,
            ),
            enabled=False,
        ),
        _policy(
            "after-only",
            conditions=Condition(
                field="tool_args.approved_amount",
                operator=ConditionOperator.GT,
                value=0,
            ),
            event=TriggerEvent.AFTER_TOOL_CALL,
        ),
    ]
    result = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={"approved_amount": 9999}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    assert result.decision == DecisionType.ALLOW


def test_agent_id_on_trigger_matches_only_that_agent() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        Policy(
            id="loan-agent-only",
            enabled=True,
            trigger=PolicyTrigger(
                event=TriggerEvent.BEFORE_TOOL_CALL,
                tool_id="approve_loan",
                agent_id="loan-agent",
            ),
            conditions=Condition(
                field="tool_args.approved_amount",
                operator=ConditionOperator.GT,
                value=0,
            ),
            action=PolicyAction(type=ActionType.BLOCK, message="loan agent rule"),
        )
    ]
    blocked = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={"approved_amount": 100}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
        agent_id="loan-agent",
    )
    allowed = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={"approved_amount": 100}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
        agent_id="compliance-agent",
    )
    missing_agent = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={"approved_amount": 100}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
        agent_id=None,
    )
    assert blocked.decision == DecisionType.BLOCK
    assert allowed.decision == DecisionType.ALLOW
    assert missing_agent.decision == DecisionType.ALLOW


def test_agent_id_ne_condition_blocks_wrong_agent() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        Policy(
            id="allowlist",
            enabled=True,
            trigger=PolicyTrigger(
                event=TriggerEvent.BEFORE_TOOL_CALL,
                tool_id="approve_loan",
            ),
            conditions=Condition(
                field="agent_id",
                operator=ConditionOperator.NE,
                value="loan-agent",
            ),
            action=PolicyAction(type=ActionType.BLOCK, message="wrong agent"),
        )
    ]
    blocked = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={}, agent_id="compliance-agent"),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
        agent_id="compliance-agent",
    )
    allowed = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={}, agent_id="loan-agent"),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
        agent_id="loan-agent",
    )
    assert blocked.decision == DecisionType.BLOCK
    assert allowed.decision == DecisionType.ALLOW


def test_before_final_response_contains() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        Policy(
            id="safe-response",
            enabled=True,
            trigger=PolicyTrigger(event=TriggerEvent.BEFORE_FINAL_RESPONSE),
            conditions=Condition(
                field="final_response",
                operator=ConditionOperator.CONTAINS,
                value="guaranteed approval",
            ),
            action=PolicyAction(type=ActionType.BLOCK, message="unsafe"),
        )
    ]
    blocked = evaluator.evaluate(
        "",
        _ctx(final_response="We offer guaranteed approval."),
        policies,
        trigger_event=TriggerEvent.BEFORE_FINAL_RESPONSE,
        agent_id="loan-agent",
    )
    allowed = evaluator.evaluate(
        "",
        _ctx(final_response="Application received."),
        policies,
        trigger_event=TriggerEvent.BEFORE_FINAL_RESPONSE,
        agent_id="loan-agent",
    )
    assert blocked.decision == DecisionType.BLOCK
    assert allowed.decision == DecisionType.ALLOW


def test_contains_is_case_insensitive_by_default() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        Policy(
            id="contains-default-insensitive",
            enabled=True,
            trigger=PolicyTrigger(event=TriggerEvent.BEFORE_FINAL_RESPONSE),
            conditions=Condition(
                field="final_response",
                operator=ConditionOperator.CONTAINS,
                value="guaranteed approval",
            ),
            action=PolicyAction(type=ActionType.BLOCK, message="unsafe"),
        )
    ]
    blocked = evaluator.evaluate(
        "",
        _ctx(final_response="We offer GUARANTEED APPROVAL right now."),
        policies,
        trigger_event=TriggerEvent.BEFORE_FINAL_RESPONSE,
    )
    assert blocked.decision == DecisionType.BLOCK


def test_contains_can_be_case_sensitive() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        Policy(
            id="contains-sensitive",
            enabled=True,
            trigger=PolicyTrigger(event=TriggerEvent.BEFORE_FINAL_RESPONSE),
            conditions=Condition(
                field="final_response",
                operator=ConditionOperator.CONTAINS,
                value="guaranteed approval",
                case_sensitive=True,
            ),
            action=PolicyAction(type=ActionType.BLOCK, message="unsafe"),
        )
    ]
    allowed = evaluator.evaluate(
        "",
        _ctx(final_response="We offer GUARANTEED APPROVAL right now."),
        policies,
        trigger_event=TriggerEvent.BEFORE_FINAL_RESPONSE,
    )
    blocked = evaluator.evaluate(
        "",
        _ctx(final_response="we offer guaranteed approval right now"),
        policies,
        trigger_event=TriggerEvent.BEFORE_FINAL_RESPONSE,
    )
    assert allowed.decision == DecisionType.ALLOW
    assert blocked.decision == DecisionType.BLOCK


def test_regex_operator_matches_case_insensitive_by_default() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        Policy(
            id="regex-insensitive",
            enabled=True,
            trigger=PolicyTrigger(event=TriggerEvent.BEFORE_FINAL_RESPONSE),
            conditions=Condition(
                field="final_response",
                operator=ConditionOperator.REGEX,
                value=r"guaranteed\s+approval",
            ),
            action=PolicyAction(type=ActionType.BLOCK, message="unsafe"),
        )
    ]
    blocked = evaluator.evaluate(
        "",
        _ctx(final_response="This is GUARANTEED   APPROVAL."),
        policies,
        trigger_event=TriggerEvent.BEFORE_FINAL_RESPONSE,
    )
    assert blocked.decision == DecisionType.BLOCK


def test_regex_can_be_case_sensitive() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        Policy(
            id="regex-sensitive",
            enabled=True,
            trigger=PolicyTrigger(event=TriggerEvent.BEFORE_FINAL_RESPONSE),
            conditions=Condition(
                field="final_response",
                operator=ConditionOperator.REGEX,
                value=r"guaranteed\s+approval",
                case_sensitive=True,
            ),
            action=PolicyAction(type=ActionType.BLOCK, message="unsafe"),
        )
    ]
    allowed = evaluator.evaluate(
        "",
        _ctx(final_response="This is GUARANTEED APPROVAL."),
        policies,
        trigger_event=TriggerEvent.BEFORE_FINAL_RESPONSE,
    )
    blocked = evaluator.evaluate(
        "",
        _ctx(final_response="This is guaranteed approval."),
        policies,
        trigger_event=TriggerEvent.BEFORE_FINAL_RESPONSE,
    )
    assert allowed.decision == DecisionType.ALLOW
    assert blocked.decision == DecisionType.BLOCK


def test_tool_metadata_available_in_context() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        _policy(
            "high-risk-side-effect",
            conditions=Condition(
                all=[
                    Condition(
                        field="tool.risk_level",
                        operator=ConditionOperator.EQ,
                        value="high",
                    ),
                    Condition(
                        field="tool.side_effect",
                        operator=ConditionOperator.EQ,
                        value=True,
                    ),
                ]
            ),
            action_type=ActionType.BLOCK,
        )
    ]
    blocked = evaluator.evaluate(
        "approve_loan",
        _ctx(tool={"risk_level": "high", "side_effect": True}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    allowed = evaluator.evaluate(
        "approve_loan",
        _ctx(tool={"risk_level": "low", "side_effect": True}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    assert blocked.decision == DecisionType.BLOCK
    assert allowed.decision == DecisionType.ALLOW


def test_after_tool_call_escalate_decision() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        Policy(
            id="escalate-after",
            enabled=True,
            trigger=PolicyTrigger(
                event=TriggerEvent.AFTER_TOOL_CALL,
                tool_id="approve_loan",
            ),
            conditions=Condition(
                field="tool_result.status",
                operator=ConditionOperator.EQ,
                value="approved",
            ),
            action=PolicyAction(type=ActionType.ESCALATE, message="needs audit"),
        )
    ]
    result = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_result={"status": "approved"}),
        policies,
        trigger_event=TriggerEvent.AFTER_TOOL_CALL,
    )
    assert result.decision == DecisionType.ESCALATE


def test_condition_all_group() -> None:
    evaluator = PolicyEvaluator()
    policies = [
        _policy(
            "combo",
            conditions=Condition(
                all=[
                    Condition(
                        field="tool_args.approved_amount",
                        operator=ConditionOperator.GT,
                        value=1000,
                    ),
                    Condition(
                        field="tool_args.approval_mode",
                        operator=ConditionOperator.EQ,
                        value="auto",
                    ),
                ]
            ),
        )
    ]
    match = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={"approved_amount": 5000, "approval_mode": "auto"}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    no_match = evaluator.evaluate(
        "approve_loan",
        _ctx(tool_args={"approved_amount": 5000, "approval_mode": "manual"}),
        policies,
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    assert match.decision == DecisionType.BLOCK
    assert no_match.decision == DecisionType.ALLOW
