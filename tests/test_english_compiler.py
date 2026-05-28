from __future__ import annotations

from pathlib import Path

import yaml

from openagentpolicy.inventory.schema import Agent, ArgumentSchema, Inventory, Tool
from openagentpolicy.policies.compiler import PolicyCompiler
from openagentpolicy.policies.providers import PolicyProvider
from openagentpolicy.policies.schema import (
    ActionType,
    CompileStatus,
    ConditionOperator,
    PolicyDocument,
    PolicyType,
    TriggerEvent,
)
from openagentpolicy.runtime.decisions import DecisionType
from openagentpolicy.runtime.engine import PolicyRuntime
from openagentpolicy.runtime.evaluator import PolicyEvaluator, build_evaluation_context
from openagentpolicy.runtime.events import PolicyEvent


def _loan_inventory() -> Inventory:
    return Inventory(
        tools=[
            Tool(
                id="approve_loan",
                name="Approve Loan",
                arguments={
                    "approved_amount": ArgumentSchema(
                        type="number",
                        aliases=["approved amount", "loan amount"],
                    ),
                    "approval_mode": ArgumentSchema(
                        type="string",
                        allowed_values=["auto", "manual"],
                        aliases=["approval mode"],
                    ),
                },
            )
        ]
    )


def test_english_policy_above_compiles_to_structured() -> None:
    inventory = _loan_inventory()
    document = PolicyDocument(
        id="policy_auto_approval_threshold",
        name="Auto Approval Threshold",
        enabled=True,
        policy_type=PolicyType.ENGLISH,
        english=(
            "If approved amount is greater than 5000, "
            "auto approval is not allowed."
        ),
        hints={
            "action": {
                "type": "block",
                "message": "Auto approval is not allowed above 5000.",
            }
        },
    )

    result = PolicyCompiler(inventory).compile_document(document)

    assert result.compile_status == CompileStatus.COMPILED
    assert result.compiled_policy is not None
    assert result.confidence > 0
    assert "approved amount" in result.resolved_terms
    assert "auto approval" in result.resolved_terms
    assert result.missing_fields == []

    policy = result.compiled_policy
    assert policy.policy_type == PolicyType.STRUCTURED
    assert policy.trigger is not None
    assert policy.trigger.tool_id == "approve_loan"
    assert policy.action is not None
    assert policy.action.type == ActionType.BLOCK
    assert policy.action.message == "Auto approval is not allowed above 5000."

    assert policy.conditions is not None
    assert policy.conditions.all is not None
    fields = {leaf.field for leaf in policy.conditions.all if leaf.is_leaf}
    assert "tool_args.approved_amount" in fields
    assert "tool_args.approval_mode" in fields

    amount_cond = next(
        c
        for c in policy.conditions.all
        if c.field == "tool_args.approved_amount"
    )
    assert amount_cond.operator == ConditionOperator.GT
    assert amount_cond.value == 5000


def test_english_agent_only_allowlist_compiles() -> None:
    inventory = Inventory(
        agents=[
            Agent(id="loan-agent", name="Loan Agent"),
            Agent(id="compliance-agent", name="Compliance Agent"),
        ],
        tools=[
            Tool(id="approve_loan", name="Approve Loan", arguments={}),
        ],
    )
    document = PolicyDocument(
        id="agent_only_loan_agent",
        policy_type=PolicyType.ENGLISH,
        english="Only loan-agent may call approve loan.",
        hints={
            "action": {
                "type": "block",
                "message": "Only loan-agent may approve loans.",
            }
        },
    )

    result = PolicyCompiler(inventory).compile_document(document)

    assert result.compile_status == CompileStatus.COMPILED
    assert result.compiled_policy is not None
    policy = result.compiled_policy
    assert policy.trigger is not None
    assert policy.trigger.tool_id == "approve_loan"
    assert policy.trigger.agent_id is None
    assert policy.conditions is not None
    assert policy.conditions.field == "agent_id"
    assert policy.conditions.operator == ConditionOperator.NE
    assert policy.conditions.value == "loan-agent"


def test_missing_kyc_field_returns_not_enforceable() -> None:
    inventory = _loan_inventory()
    document = PolicyDocument(
        id="policy_kyc_check",
        policy_type=PolicyType.ENGLISH,
        english="If KYC status is missing, the request must be blocked.",
        hints={"action": {"type": "block", "message": "KYC required"}},
    )

    result = PolicyCompiler(inventory).compile_document(document)

    assert result.compile_status == CompileStatus.NOT_ENFORCEABLE
    assert result.compiled_policy is None
    assert any("kyc" in field.lower() for field in result.missing_fields)


def test_compiled_english_policy_blocks_runtime_event(tmp_path: Path) -> None:
    root = tmp_path / "app"
    policies_dir = root / "policies"
    policies_dir.mkdir(parents=True)

    (root / "inventory.yaml").write_text(
        yaml.dump(
            {
                "tools": [
                    {
                        "id": "approve_loan",
                        "arguments": {
                            "approved_amount": {
                                "type": "number",
                                "aliases": ["approved amount"],
                            },
                            "approval_mode": {
                                "type": "string",
                                "allowed_values": ["auto", "manual"],
                            },
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (policies_dir / "auto_approval.yaml").write_text(
        yaml.dump(
            {
                "id": "policy_auto_approval_threshold",
                "enabled": True,
                "policy_type": "english",
                "english": (
                    "If approved amount is greater than 5000, "
                    "auto approval is not allowed."
                ),
                "hints": {
                    "action": {
                        "type": "block",
                        "message": "Auto approval is not allowed above 5000.",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "openagentpolicy.yaml").write_text(
        yaml.dump(
            {
                "inventory": {"provider": "file", "path": "./inventory.yaml"},
                "policies": {
                    "provider": "directory",
                    "path": "./policies",
                    "support_english": True,
                    "compile_on_startup": True,
                },
            }
        ),
        encoding="utf-8",
    )

    runtime = PolicyRuntime.from_config(root / "openagentpolicy.yaml")
    assert len(runtime.policies) == 1

    event = PolicyEvent(
        event_type=TriggerEvent.BEFORE_TOOL_CALL.value,
        tool_id="approve_loan",
        tool_args={"approved_amount": 9000, "approval_mode": "auto"},
    )
    decision = runtime.process_event(event)
    assert decision.decision == DecisionType.BLOCK
    assert "policy_auto_approval_threshold" in decision.matched_policies


def test_compiled_policy_blocks_via_evaluator() -> None:
    inventory = _loan_inventory()
    document = PolicyDocument(
        id="policy_auto_approval_threshold",
        policy_type=PolicyType.ENGLISH,
        english=(
            "If approved amount is greater than 5000, "
            "auto approval is not allowed."
        ),
        hints={
            "action": {
                "type": "block",
                "message": "Auto approval is not allowed above 5000.",
            }
        },
    )
    result = PolicyCompiler(inventory).compile_document(document)
    assert result.compiled_policy is not None

    evaluator = PolicyEvaluator()
    ctx = build_evaluation_context(
        tool_args={"approved_amount": 7500, "approval_mode": "auto"}
    )
    block = evaluator.evaluate(
        "approve_loan",
        ctx,
        [result.compiled_policy],
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    allow = evaluator.evaluate(
        "approve_loan",
        build_evaluation_context(
            tool_args={"approved_amount": 1000, "approval_mode": "auto"}
        ),
        [result.compiled_policy],
        trigger_event=TriggerEvent.BEFORE_TOOL_CALL,
    )
    assert block.decision == DecisionType.BLOCK
    assert allow.decision == DecisionType.ALLOW


def test_policy_provider_skips_not_enforceable(tmp_path: Path) -> None:
    policies_dir = tmp_path / "policies"
    policies_dir.mkdir()
    (policies_dir / "kyc.yaml").write_text(
        yaml.dump(
            {
                "id": "policy_kyc",
                "policy_type": "english",
                "english": "If KYC level is high, block.",
            }
        ),
        encoding="utf-8",
    )

    from openagentpolicy.config import PoliciesConfig

    provider = PolicyProvider(
        PoliciesConfig(provider="directory", path="policies", support_english=True),
        tmp_path,
        inventory=_loan_inventory(),
    )
    policies, results = provider.load_policies_with_results()
    assert policies == []
    assert results[0].compile_status == CompileStatus.NOT_ENFORCEABLE
