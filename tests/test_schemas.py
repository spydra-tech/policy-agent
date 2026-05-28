import pytest
from pydantic import ValidationError

from openagentpolicy.inventory.schema import (
    Agent,
    Application,
    ArgumentSchema,
    Inventory,
    RiskLevel,
    Tool,
)
from openagentpolicy.policies.schema import (
    ActionType,
    Condition,
    ConditionOperator,
    Policy,
    PolicyAction,
    PolicyTrigger,
    PolicyType,
    TriggerEvent,
)
from openagentpolicy.runtime.decisions import DecisionType, PolicyDecision
from openagentpolicy.runtime.events import PolicyEvent


def test_application_schema() -> None:
    app = Application(id="app-1", name="Demo", environment="dev")
    assert app.id == "app-1"
    assert app.environment == "dev"


def test_tool_with_arguments() -> None:
    tool = Tool(
        id="approve_loan",
        name="Approve Loan",
        side_effect=True,
        risk_level=RiskLevel.HIGH,
        arguments={
            "amount": ArgumentSchema(
                type="number",
                description="Loan amount",
                allowed_values=None,
            )
        },
    )
    assert tool.side_effect is True
    assert tool.arguments["amount"].type == "number"


def test_inventory_get_tool_by_id_or_name() -> None:
    inv = Inventory(
        tools=[
            Tool(id="tool-a", name="Tool A"),
            Tool(id="tool-b"),
        ]
    )
    assert inv.get_tool("tool-a") is not None
    assert inv.get_tool("Tool A") is not None
    assert inv.get_tool("missing") is None


def test_structured_policy_valid() -> None:
    policy = Policy(
        id="p1",
        trigger=PolicyTrigger(
            event=TriggerEvent.BEFORE_TOOL_CALL,
            tool_id="approve_loan",
        ),
        conditions=Condition(
            field="amount",
            operator=ConditionOperator.GT,
            value=10000,
        ),
        action=PolicyAction(type=ActionType.BLOCK, message="Too large"),
    )
    assert policy.enabled is True
    assert policy.policy_type == PolicyType.STRUCTURED


def test_english_policy_requires_text() -> None:
    from openagentpolicy.policies.schema import PolicyDocument

    with pytest.raises(ValidationError):
        PolicyDocument(id="p1", policy_type=PolicyType.ENGLISH)


def test_english_policy_rejects_structured_fields() -> None:
    from openagentpolicy.policies.schema import PolicyDocument

    with pytest.raises(ValidationError):
        PolicyDocument(
            id="p1",
            policy_type=PolicyType.ENGLISH,
            english="block high risk",
            trigger=PolicyTrigger(event=TriggerEvent.BEFORE_TOOL_CALL),
            action=PolicyAction(type=ActionType.BLOCK),
        )


def test_structured_policy_requires_trigger_and_action() -> None:
    with pytest.raises(ValidationError):
        Policy(id="p1", policy_type=PolicyType.STRUCTURED)


def test_structured_policy_rejects_english_text() -> None:
    with pytest.raises(ValidationError):
        Policy(
            id="p1",
            policy_type=PolicyType.STRUCTURED,
            english="do not allow",
            trigger=PolicyTrigger(event=TriggerEvent.BEFORE_TOOL_CALL, tool_id="approve_loan"),
            action=PolicyAction(type=ActionType.BLOCK),
        )


def test_condition_leaf_requires_operator() -> None:
    with pytest.raises(ValidationError):
        Condition(field="amount")


def test_condition_cannot_mix_leaf_and_group() -> None:
    with pytest.raises(ValidationError):
        Condition(
            field="amount",
            operator=ConditionOperator.GT,
            value=1,
            all=[Condition(field="x", operator=ConditionOperator.EXISTS)],
        )


def test_condition_all_group() -> None:
    group = Condition(
        all=[
            Condition(field="a", operator=ConditionOperator.EQ, value=1),
            Condition(field="b", operator=ConditionOperator.EQ, value=2),
        ]
    )
    assert group.all is not None
    assert len(group.all) == 2


def test_condition_not_group() -> None:
    group = Condition(
        not_=Condition(field="blocked", operator=ConditionOperator.EXISTS)
    )
    assert group.not_ is not None


def test_modify_args_action_requires_set() -> None:
    with pytest.raises(ValidationError):
        PolicyAction(type=ActionType.MODIFY_ARGS)


def test_policy_event_defaults() -> None:
    event = PolicyEvent(event_type="before_tool_call", tool_id="t1")
    assert event.tool_args == {}
    assert event.metadata == {}


def test_policy_decision_schema() -> None:
    decision = PolicyDecision(
        decision=DecisionType.BLOCK,
        matched_policies=["p1", "p2"],
        message="blocked",
        modified_args={"amount": 100},
    )
    assert decision.matched_policies == ["p1", "p2"]
