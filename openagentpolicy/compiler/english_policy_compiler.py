from __future__ import annotations

from typing import Any

from openagentpolicy.compiler.compile_result import (
    CompileError,
    CompileResult,
    CompileResultStatus,
    CompilerMetadata,
    Enforceability,
)
from openagentpolicy.compiler.enforceability import validate_enforceability
from openagentpolicy.compiler.test_case_generator import generate_test_cases
from openagentpolicy.inventory.schema import Inventory
from openagentpolicy.policies.compiler import PolicyCompiler
from openagentpolicy.policies.schema import (
    CompileStatus,
    PolicyAction,
    PolicyDocument,
    PolicyType,
)
from openagentpolicy.runtime.evaluator import PolicyEvaluator, build_evaluation_context


class EnglishPolicyCompiler:
    def __init__(self, inventory: Inventory) -> None:
        self.inventory = inventory
        self._compiler = PolicyCompiler(inventory)

    def compile(
        self,
        *,
        english: str,
        policy_id: str | None = None,
        action_hint: dict[str, Any] | None = None,
        hints: dict[str, Any] | None = None,
    ) -> CompileResult:
        pid = policy_id or "compiled_policy"
        merged_hints = dict(hints or {})
        if action_hint is not None:
            merged_hints["action"] = action_hint
        doc = PolicyDocument(
            id=pid,
            policy_type=PolicyType.ENGLISH,
            english=english,
            hints=merged_hints or None,
        )
        result = self._compiler.compile_document(doc)
        metadata = CompilerMetadata(compiler_type="rule_based")

        if result.compile_status != CompileStatus.COMPILED or result.compiled_policy is None:
            status = (
                CompileResultStatus.NOT_ENFORCEABLE
                if result.compile_status == CompileStatus.NOT_ENFORCEABLE
                else CompileResultStatus.NEEDS_REVIEW
            )
            return CompileResult(
                status=status,
                enforceability=Enforceability.NOT_ENFORCEABLE
                if status == CompileResultStatus.NOT_ENFORCEABLE
                else Enforceability.NEEDS_REVIEW,
                policy_id=pid,
                english=english,
                resolved_terms=result.resolved_terms,
                missing_terms=result.missing_fields,
                errors=[
                    CompileError(
                        code="MISSING_INVENTORY_FIELD"
                        if result.missing_fields
                        else "COMPILATION_FAILED",
                        message=result.message or "Policy is not enforceable",
                    )
                ],
                suggested_fixes=_default_fixes(result.missing_fields),
                compiler_metadata=metadata,
            )

        compiled = result.compiled_policy.model_copy(
            update={
                "policy_type": PolicyType.COMPILED,
                "source": {
                    "english": english,
                    "compiled_at": metadata.compiled_at.isoformat(),
                    "compiler_version": metadata.compiler_version,
                },
                "validation": {"enforceability": "enforceable"},
            }
        )
        enforce_errors = validate_enforceability(compiled, self.inventory)
        if enforce_errors:
            return CompileResult(
                status=CompileResultStatus.NOT_ENFORCEABLE,
                enforceability=Enforceability.NOT_ENFORCEABLE,
                policy_id=pid,
                english=english,
                compiled_policy=compiled,
                resolved_terms=result.resolved_terms,
                missing_terms=result.missing_fields,
                errors=[
                    CompileError(code="UNRESOLVED_FIELD", message=msg)
                    for msg in enforce_errors
                ],
                compiler_metadata=metadata,
                suggested_fixes=_default_fixes(result.missing_fields),
            )

        test_cases = generate_test_cases(compiled)
        case_errors = _run_test_cases(compiled, test_cases)
        if case_errors:
            return CompileResult(
                status=CompileResultStatus.NEEDS_REVIEW,
                enforceability=Enforceability.NEEDS_REVIEW,
                policy_id=pid,
                english=english,
                compiled_policy=compiled,
                resolved_terms=result.resolved_terms,
                test_cases=test_cases,
                errors=[CompileError(code="TEST_CASE_FAILED", message=e) for e in case_errors],
                compiler_metadata=metadata,
            )

        return CompileResult(
            status=CompileResultStatus.COMPILED,
            enforceability=Enforceability.ENFORCEABLE,
            policy_id=pid,
            english=english,
            compiled_policy=compiled,
            resolved_terms=result.resolved_terms,
            missing_terms=result.missing_fields,
            test_cases=test_cases,
            compiler_metadata=metadata,
        )


def _run_test_cases(policy: Any, test_cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    evaluator = PolicyEvaluator()
    trigger = policy.trigger.event
    for case in test_cases:
        event = case["event"]
        decision = evaluator.evaluate(
            event.get("tool_id", ""),
            build_evaluation_context(
                tool_args=event.get("tool_args", {}),
                tool_result=event.get("tool_result"),
                tool={},
                metadata=event.get("metadata"),
                final_response=event.get("final_response"),
                agent_id=event.get("agent_id"),
            ),
            [policy],
            trigger_event=trigger,
            agent_id=event.get("agent_id"),
        )
        if decision.decision.value != case["expected_decision"]:
            errors.append(
                f"{case['name']}: expected {case['expected_decision']} got {decision.decision.value}"
            )
    return errors


def _default_fixes(missing_fields: list[str]) -> list[str]:
    if not missing_fields:
        return ["Review the policy wording and provide explicit action hints."]
    return [
        "Add missing fields to inventory.",
        "Generate inventory from traces that include these fields.",
        "Map unresolved terms to existing inventory aliases.",
    ]
