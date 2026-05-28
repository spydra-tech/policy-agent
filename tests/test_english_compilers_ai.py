from __future__ import annotations

from openagentpolicy.inventory.schema import ArgumentSchema, Inventory, Tool
from openagentpolicy.policies.english_compilers import (
    AIEnglishCompiler,
    HybridEnglishCompiler,
    RuleBasedEnglishCompiler,
)
from openagentpolicy.policies.schema import (
    CompileStatus,
    PolicyDocument,
    PolicyType,
)


class _FakeTranslator:
    def __init__(self, payload: dict | None) -> None:
        self.payload = payload

    def translate(self, **_: object) -> dict | None:
        return self.payload


def _inventory() -> Inventory:
    return Inventory(
        tools=[
            Tool(
                id="approve_loan",
                arguments={
                    "approved_amount": ArgumentSchema(type="number"),
                    "approval_mode": ArgumentSchema(
                        type="string", allowed_values=["auto", "manual"]
                    ),
                },
            )
        ]
    )


def test_ai_compiler_compiles_when_deterministic_compiler_agrees() -> None:
    document = PolicyDocument(
        id="p1",
        policy_type=PolicyType.ENGLISH,
        english="If approved amount is greater than 5000, auto approval is not allowed.",
    )
    translator = _FakeTranslator(
        {
            "policy": {
                "id": "p1",
                "policy_type": "structured",
                "trigger": {"event": "before_tool_call", "tool_id": "approve_loan"},
                "conditions": {
                    "all": [
                        {
                            "field": "tool_args.approved_amount",
                            "operator": ">",
                            "value": 5000,
                        },
                        {
                            "field": "tool_args.approval_mode",
                            "operator": "==",
                            "value": "auto",
                        },
                    ]
                },
                "action": {"type": "block", "message": "Too high"},
            },
        }
    )
    compiler = AIEnglishCompiler(_inventory(), translator=translator)
    result = compiler.compile_document(document)
    assert result.compile_status == CompileStatus.COMPILED
    assert result.confidence == 1.0
    assert result.compiled_policy is not None
    assert result.compiled_policy.trigger is not None
    assert result.compiled_policy.trigger.tool_id == "approve_loan"


def test_self_reported_confidence_is_not_the_gate() -> None:
    # Model claims high confidence but its structured output disagrees with the
    # deterministic compiler (drops the approval_mode condition). Self-reported
    # confidence must NOT promote this to compiled; it goes to needs_review.
    document = PolicyDocument(
        id="p2",
        policy_type=PolicyType.ENGLISH,
        english="If approved amount is greater than 5000, auto approval is not allowed.",
    )
    translator = _FakeTranslator(
        {
            "policy": {
                "id": "p2",
                "policy_type": "structured",
                "trigger": {"event": "before_tool_call", "tool_id": "approve_loan"},
                "conditions": {
                    "field": "tool_args.approved_amount",
                    "operator": ">",
                    "value": 5000,
                },
                "action": {"type": "block"},
            },
            "confidence": 0.99,
        }
    )
    compiler = AIEnglishCompiler(_inventory(), translator=translator)
    result = compiler.compile_document(document)
    assert result.compile_status == CompileStatus.NEEDS_REVIEW
    assert result.compiled_policy is not None


def test_ai_only_output_without_corroboration_needs_review() -> None:
    # The deterministic compiler cannot handle metadata-based rules, so even a
    # schema-valid, inventory-aligned AI policy is left for human review rather
    # than auto-activated.
    document = PolicyDocument(
        id="p_meta",
        policy_type=PolicyType.ENGLISH,
        english="Block approvals when the request region is restricted.",
    )
    translator = _FakeTranslator(
        {
            "policy": {
                "id": "p_meta",
                "policy_type": "structured",
                "trigger": {"event": "before_tool_call", "tool_id": "approve_loan"},
                "conditions": {
                    "field": "metadata.region",
                    "operator": "==",
                    "value": "restricted",
                },
                "action": {"type": "block"},
            },
            "confidence": 0.97,
        }
    )
    compiler = AIEnglishCompiler(_inventory(), translator=translator)
    result = compiler.compile_document(document)
    assert result.compile_status == CompileStatus.NEEDS_REVIEW
    assert result.compiled_policy is not None


def test_ai_compiler_rejects_unknown_inventory_fields() -> None:
    document = PolicyDocument(
        id="p3",
        policy_type=PolicyType.ENGLISH,
        english="Block high loan risk.",
    )
    translator = _FakeTranslator(
        {
            "policy": {
                "id": "p3",
                "policy_type": "structured",
                "trigger": {"event": "before_tool_call", "tool_id": "approve_loan"},
                "conditions": {
                    "field": "tool_args.risk_score",
                    "operator": ">",
                    "value": 0.8,
                },
                "action": {"type": "block"},
            },
            "confidence": 0.99,
        }
    )
    compiler = AIEnglishCompiler(
        _inventory(),
        translator=translator,
    )
    result = compiler.compile_document(document)
    assert result.compile_status == CompileStatus.NOT_ENFORCEABLE
    assert "Unknown argument" in (result.message or "")


def test_hybrid_falls_back_to_rule_based_when_ai_not_compiled() -> None:
    document = PolicyDocument(
        id="p4",
        policy_type=PolicyType.ENGLISH,
        english="If approved amount is greater than 5000, auto approval is not allowed.",
        hints={"action": {"type": "block", "message": "Too high"}},
    )
    ai_compiler = AIEnglishCompiler(
        _inventory(),
        translator=_FakeTranslator(None),
    )
    hybrid = HybridEnglishCompiler(
        primary=ai_compiler,
        fallback=RuleBasedEnglishCompiler(_inventory()),
    )
    result = hybrid.compile_document(document)
    assert result.compile_status == CompileStatus.COMPILED
    assert result.compiled_policy is not None


def test_hybrid_defers_to_deterministic_when_ai_unavailable() -> None:
    # When the AI translator is unavailable (no signal), the hybrid result must
    # reflect the deterministic outcome (not_enforceable here) rather than be
    # masked by a generic "AI unavailable" needs_review.
    document = PolicyDocument(
        id="p5",
        policy_type=PolicyType.ENGLISH,
        english="If KYC level is high, block.",
    )
    hybrid = HybridEnglishCompiler(
        primary=AIEnglishCompiler(_inventory(), translator=_FakeTranslator(None)),
        fallback=RuleBasedEnglishCompiler(_inventory()),
    )
    result = hybrid.compile_document(document)
    assert result.compile_status == CompileStatus.NOT_ENFORCEABLE
