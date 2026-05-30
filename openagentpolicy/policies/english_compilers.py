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


# Operator symbols accepted by the Condition schema (must match
# ConditionOperator in policies/schema.py).
_CONDITION_OPERATORS = [
    "==", "!=", ">", ">=", "<", "<=",
    "in", "not_in", "contains", "regex", "exists", "not_exists",
]

# JSON Schema describing a single structured Policy. Used as the OpenAI
# Responses structured-output format so the model is constrained to the exact
# shape rather than guessing operator names or condition envelopes. Pydantic
# validation + deterministic corroboration remain the authoritative gates; this
# just narrows the model's output space up front.
_CONDITION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Leaf {field,operator,value} OR group {all|any|not}.",
    "properties": {
        "field": {"type": ["string", "null"]},
        "operator": {"type": ["string", "null"], "enum": [*_CONDITION_OPERATORS, None]},
        "value": {"type": ["string", "number", "integer", "boolean", "array", "null"]},
        "case_sensitive": {"type": "boolean"},
        "all": {"type": ["array", "null"], "items": {"$ref": "#/$defs/condition"}},
        "any": {"type": ["array", "null"], "items": {"$ref": "#/$defs/condition"}},
        "not": {"anyOf": [{"$ref": "#/$defs/condition"}, {"type": "null"}]},
    },
}

_POLICY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "name": {"type": ["string", "null"]},
        "enabled": {"type": "boolean"},
        "policy_type": {"type": "string", "enum": ["structured"]},
        "trigger": {
            "type": "object",
            "properties": {
                "event": {
                    "type": "string",
                    "enum": [
                        "before_tool_call",
                        "after_tool_call",
                        "before_final_response",
                    ],
                },
                "tool_id": {"type": ["string", "null"]},
                "agent_id": {"type": ["string", "null"]},
            },
            "required": ["event"],
        },
        "conditions": {"$ref": "#/$defs/condition"},
        "action": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": [
                        "allow", "block", "warn", "log_only",
                        "redact_result", "escalate", "modify_args",
                    ],
                },
                "message": {"type": ["string", "null"]},
            },
            "required": ["type"],
        },
    },
    "required": ["id", "policy_type", "trigger", "conditions", "action"],
    "$defs": {"condition": _CONDITION_JSON_SCHEMA},
}


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
            "task": "Convert an English policy into ONE structured policy JSON object",
            "requirements": [
                "Return ONLY a valid JSON object, with no prose or markdown fences",
                "Set policy_type to 'structured'",
                "Use only tool ids and argument/field names present in the inventory",
                "Top-level keys: id, name, enabled, policy_type, trigger, conditions, action",
            ],
            "trigger_schema": {
                "event": "before_tool_call | after_tool_call | before_final_response",
                "tool_id": "tool id from inventory; omit for before_final_response",
                "agent_id": "optional; usually leave unset (scope by a condition instead)",
            },
            "condition_schema": {
                "leaf": {
                    "field": (
                        "dotted path: tool_args.<arg>, metadata.<key>, agent_id, "
                        "final_response, tool.risk_level, tool.side_effect"
                    ),
                    "operator": "EXACT symbol from the operators list below",
                    "value": "comparison value (omit for exists/not_exists)",
                },
                "group": 'combine leaves with {"all": [...]}, {"any": [...]}, or {"not": {...}}',
            },
            "operators": [
                "==", "!=", ">", ">=", "<", "<=",
                "in", "not_in", "contains", "regex", "exists", "not_exists",
            ],
            "operator_notes": [
                "Use the SYMBOL, never a word: 'greater than' -> '>', 'at least' -> '>=', "
                "'equals'/'is' -> '==', 'not equal'/'is not' -> '!=', 'below' -> '<'",
                "exists / not_exists take no value",
            ],
            "action_schema": {
                "type": "allow | block | warn | log_only | redact_result | escalate | modify_args",
                "message": "optional human-readable message",
            },
            "guidance": [
                "If policy_document.hints.action is present, use it as the action.",
                "Restrict a tool to one agent ('only X may call/use <tool>') with a leaf "
                "condition {field:'agent_id', operator:'!=', value:'X'} and action block — "
                "NOT trigger.agent_id and NOT a bare {agent_id: X} object.",
                "Combine multiple numeric/text constraints under 'all'.",
            ],
            "examples": [
                {
                    "english": "If approved amount is greater than 5000 and approval mode is auto, auto approval is not allowed.",
                    "policy": {
                        "id": "example_threshold",
                        "policy_type": "structured",
                        "trigger": {"event": "before_tool_call", "tool_id": "approve_loan"},
                        "conditions": {
                            "all": [
                                {"field": "tool_args.approved_amount", "operator": ">", "value": 5000},
                                {"field": "tool_args.approval_mode", "operator": "==", "value": "auto"},
                            ]
                        },
                        "action": {"type": "block", "message": "Auto approval is not allowed above 5000."},
                    },
                },
                {
                    "english": "Only loan-agent may call approve loan.",
                    "policy": {
                        "id": "example_agent_only",
                        "policy_type": "structured",
                        "trigger": {"event": "before_tool_call", "tool_id": "approve_loan"},
                        "conditions": {"field": "agent_id", "operator": "!=", "value": "loan-agent"},
                        "action": {"type": "block", "message": "Only loan-agent may approve loans."},
                    },
                },
            ],
            "inventory": inventory_payload,
            "policy_document": document.model_dump(mode="json"),
            "output_format": (
                "Return ONLY the structured policy JSON object itself (top-level "
                "keys id, name, enabled, policy_type, trigger, conditions, action)."
            ),
        }
        text = self._create(client, json.dumps(prompt))
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _create(self, client: Any, content: str) -> str | None:
        """Call the Responses API, constraining output to the policy schema.

        Falls back to an unconstrained call if the SDK/endpoint rejects the
        structured-output ``text.format`` argument, so older deployments still
        work (the prompt itself also describes the schema).
        """
        request: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "input": [{"role": "user", "content": content}],
        }
        try:
            response = client.responses.create(
                **request,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "structured_policy",
                        "schema": _POLICY_JSON_SCHEMA,
                        "strict": False,
                    }
                },
            )
        except Exception:
            response = client.responses.create(**request)
        text = getattr(response, "output_text", "") or ""
        return text.strip() or None


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
        policy_obj = _extract_policy_object(payload)
        if policy_obj is None:
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

        # Pin identity to the source document. The LLM's chosen id/name are not
        # authoritative; the enforced policy must remain traceable to the file it
        # came from (audit logs and matched_policies reference this id).
        structured = policy.model_copy(
            update={
                "policy_type": PolicyType.STRUCTURED,
                "id": document.id,
                "name": document.name or policy.name,
            }
        )
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


def _extract_policy_object(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the policy object out of a translator payload.

    Models inconsistently either wrap the policy under a ``policy`` key or emit
    the policy fields at the top level. Accept both rather than rejecting a
    structurally valid policy over its envelope.
    """
    candidate = payload.get("policy")
    if isinstance(candidate, dict):
        return candidate
    # Top-level policy: detect by its identifying keys. Extra keys like
    # "message"/"missing_fields" are ignored by Policy validation.
    if any(key in payload for key in ("trigger", "conditions", "action")):
        return payload
    return None


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
