from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from openagentpolicy.inventory.schema import Inventory
from openagentpolicy.policies.compiler import PolicyCompiler
from openagentpolicy.policies.schema import (
    CompileStatus,
    Policy,
    PolicyCompileResult,
    PolicyDocument,
    PolicyType,
)


class EnglishCompiler(Protocol):
    def compile_document(self, document: PolicyDocument) -> PolicyCompileResult: ...


class RuleBasedEnglishCompiler:
    def __init__(self, inventory: Inventory) -> None:
        self._compiler = PolicyCompiler(inventory)

    def compile_document(self, document: PolicyDocument) -> PolicyCompileResult:
        return self._compiler.compile_document(document)


class AITranslator(Protocol):
    def translate(
        self,
        *,
        document: PolicyDocument,
        inventory: Inventory,
    ) -> dict[str, Any] | None: ...


@dataclass
class OpenAITranslator:
    model: str = "gpt-4.1-mini"
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None

    def translate(
        self,
        *,
        document: PolicyDocument,
        inventory: Inventory,
    ) -> dict[str, Any] | None:
        api_key = os.getenv(self.api_key_env)
        if not api_key:
            return None
        try:
            from openai import OpenAI
        except Exception:
            return None

        client = OpenAI(api_key=api_key, base_url=self.base_url)
        inventory_payload = inventory.model_dump(mode="json")
        prompt = {
            "task": "Convert English policy into structured policy JSON",
            "requirements": [
                "Return ONLY valid JSON object",
                "Use known tool_id and fields from inventory",
                "Use policy schema fields: id,name,enabled,policy_type,trigger,conditions,action",
                "Set policy_type=structured",
            ],
            "inventory": inventory_payload,
            "policy_document": document.model_dump(mode="json"),
            "expected_output": {
                "policy": {
                    "id": "string",
                    "name": "string|optional",
                    "enabled": True,
                    "policy_type": "structured",
                    "trigger": {"event": "before_tool_call", "tool_id": "string|optional"},
                    "conditions": {},
                    "action": {"type": "allow|block|warn|log_only|modify_args|redact_result|escalate"},
                },
                "message": "optional string",
                "missing_fields": [],
            },
        }
        response = client.responses.create(
            model=self.model,
            temperature=0,
            input=[{"role": "user", "content": json.dumps(prompt)}],
        )
        text = response.output_text.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None


class AIEnglishCompiler:
    """Compile English via an LLM, but only auto-activate when grounded.

    Safety is not gated on the model's self-reported confidence (an LLM emitting
    a number about itself is not a calibrated probability). The gates are:

    1. Schema validity of the produced policy.
    2. Inventory alignment (tool/field existence).
    3. Deterministic corroboration: the rule-based compiler must independently
       produce a semantically equivalent structured policy. Agreement is the
       trust signal; without it the result is needs_review for a human.
    """

    def __init__(
        self,
        inventory: Inventory,
        *,
        translator: AITranslator,
        corroborator: "RuleBasedEnglishCompiler | None" = None,
    ) -> None:
        self.inventory = inventory
        self.translator = translator
        self._corroborator = corroborator or RuleBasedEnglishCompiler(inventory)

    def compile_document(self, document: PolicyDocument) -> PolicyCompileResult:
        payload = self.translator.translate(document=document, inventory=self.inventory)
        if not payload:
            return PolicyCompileResult(
                policy_id=document.id,
                compile_status=CompileStatus.NEEDS_REVIEW,
                confidence=0.0,
                message="AI compiler unavailable or returned empty output",
            )
        policy_obj = payload.get("policy")
        if not isinstance(policy_obj, dict):
            return PolicyCompileResult(
                policy_id=document.id,
                compile_status=CompileStatus.NEEDS_REVIEW,
                confidence=0.0,
                message="AI compiler returned invalid policy payload",
            )
        try:
            policy = Policy.model_validate(policy_obj)
        except Exception as exc:
            return PolicyCompileResult(
                policy_id=document.id,
                compile_status=CompileStatus.NEEDS_REVIEW,
                confidence=0.0,
                message=f"AI compiler produced schema-invalid policy: {exc}",
            )
        inventory_error = _validate_inventory_alignment(policy, self.inventory)
        if inventory_error:
            return PolicyCompileResult(
                policy_id=document.id,
                compile_status=CompileStatus.NOT_ENFORCEABLE,
                confidence=0.0,
                message=inventory_error,
                missing_fields=payload.get("missing_fields") or [],
            )

        structured = policy.model_copy(update={"policy_type": PolicyType.STRUCTURED})
        missing_fields = payload.get("missing_fields") or []

        # Grounded corroboration: does the deterministic compiler independently
        # agree? Agreement -> trust and auto-compile. Otherwise -> human review.
        corroboration = self._corroborator.compile_document(document)
        corroborated = (
            corroboration.compile_status == CompileStatus.COMPILED
            and corroboration.compiled_policy is not None
            and _policies_agree(structured, corroboration.compiled_policy)
        )
        if corroborated:
            return PolicyCompileResult(
                policy_id=document.id,
                compile_status=CompileStatus.COMPILED,
                confidence=1.0,
                compiled_policy=structured,
                message=payload.get("message")
                or "AI output corroborated by deterministic compiler",
                missing_fields=missing_fields,
            )
        return PolicyCompileResult(
            policy_id=document.id,
            compile_status=CompileStatus.NEEDS_REVIEW,
            confidence=0.5,
            compiled_policy=structured,
            message=payload.get("message")
            or (
                "AI output not corroborated by the deterministic compiler; "
                "requires human review before activation"
            ),
            missing_fields=missing_fields,
        )


class HybridEnglishCompiler:
    def __init__(
        self,
        *,
        primary: AIEnglishCompiler,
        fallback: RuleBasedEnglishCompiler,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    def compile_document(self, document: PolicyDocument) -> PolicyCompileResult:
        ai_result = self.primary.compile_document(document)
        if ai_result.compile_status == CompileStatus.COMPILED:
            return ai_result
        fallback_result = self.fallback.compile_document(document)
        if fallback_result.compile_status == CompileStatus.COMPILED:
            return fallback_result
        # Prefer a genuine AI candidate that a human should review (it produced a
        # schema-valid, inventory-aligned policy that simply wasn't corroborated).
        # A bare needs_review with no policy means "no AI signal" (e.g. the
        # translator is unavailable), so defer to the deterministic result.
        if (
            ai_result.compile_status == CompileStatus.NEEDS_REVIEW
            and ai_result.compiled_policy is not None
        ):
            return ai_result
        return fallback_result


def create_english_compiler(
    *,
    mode: str,
    inventory: Inventory,
    ai_config: dict[str, Any] | None = None,
) -> EnglishCompiler:
    normalized = mode.strip().lower()
    rule_based = RuleBasedEnglishCompiler(inventory)
    if normalized == "rule_based":
        return rule_based

    ai_settings = ai_config or {}
    translator = OpenAITranslator(
        model=ai_settings.get("model", "gpt-4.1-mini"),
        api_key_env=ai_settings.get("api_key_env", "OPENAI_API_KEY"),
        base_url=ai_settings.get("base_url"),
    )
    ai_compiler = AIEnglishCompiler(
        inventory,
        translator=translator,
        corroborator=rule_based,
    )
    if normalized == "ai":
        return ai_compiler
    if normalized == "hybrid":
        return HybridEnglishCompiler(primary=ai_compiler, fallback=rule_based)
    return rule_based


def _validate_inventory_alignment(policy: Policy, inventory: Inventory) -> str | None:
    trigger = policy.trigger
    if trigger and trigger.tool_id and inventory.get_tool(trigger.tool_id) is None:
        return f"Unknown tool_id in compiled policy: {trigger.tool_id}"
    if policy.conditions is None:
        return None
    fields = _collect_condition_fields(policy.conditions)
    for field in fields:
        if field in {"agent_id", "final_response"}:
            continue
        if field.startswith("metadata.") or field.startswith("tool_result."):
            continue
        if field.startswith("tool_args."):
            if trigger is None or not trigger.tool_id:
                return f"Condition field {field} requires trigger.tool_id"
            tool = inventory.get_tool(trigger.tool_id)
            if tool is None:
                return f"Unknown tool in trigger for field validation: {trigger.tool_id}"
            arg_name = field.split(".", 1)[1]
            if arg_name not in tool.arguments:
                return f"Unknown argument '{arg_name}' for tool '{trigger.tool_id}'"
            continue
        return f"Unsupported condition field path: {field}"
    return None


def _policies_agree(a: Policy, b: Policy) -> bool:
    """Semantic equivalence of two structured policies (message text aside)."""
    if a.trigger is None or b.trigger is None:
        return False
    if a.trigger.event != b.trigger.event:
        return False
    if (a.trigger.tool_id or None) != (b.trigger.tool_id or None):
        return False
    if (a.trigger.agent_id or None) != (b.trigger.agent_id or None):
        return False
    if a.action is None or b.action is None:
        return False
    if a.action.type != b.action.type:
        return False
    return _canonical_condition(a.conditions) == _canonical_condition(b.conditions)


def _canonical_condition(condition: Any) -> Any:
    """Order-independent canonical form of a condition tree for comparison."""
    if condition is None:
        return None
    if getattr(condition, "is_leaf", False) and getattr(condition, "field", None):
        operator = condition.operator.value if condition.operator else None
        return (
            "leaf",
            condition.field,
            operator,
            _normalize_value(condition.value),
            bool(getattr(condition, "case_sensitive", False)),
        )
    parts: list[Any] = []
    if getattr(condition, "all", None):
        parts.append(
            (
                "all",
                tuple(
                    sorted(
                        (_canonical_condition(c) for c in condition.all), key=repr
                    )
                ),
            )
        )
    if getattr(condition, "any", None):
        parts.append(
            (
                "any",
                tuple(
                    sorted(
                        (_canonical_condition(c) for c in condition.any), key=repr
                    )
                ),
            )
        )
    not_group = getattr(condition, "not_", None)
    if not_group is not None:
        parts.append(("not", _canonical_condition(not_group)))
    if len(parts) == 1:
        return parts[0]
    return ("group", tuple(sorted(parts, key=repr)))


def _normalize_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def _collect_condition_fields(condition: Any) -> list[str]:
    fields: list[str] = []
    field = getattr(condition, "field", None)
    if field:
        fields.append(field)
    for group_name in ("all", "any"):
        group = getattr(condition, group_name, None) or []
        for child in group:
            fields.extend(_collect_condition_fields(child))
    not_group = getattr(condition, "not_", None)
    if not_group is not None:
        fields.extend(_collect_condition_fields(not_group))
    return fields
