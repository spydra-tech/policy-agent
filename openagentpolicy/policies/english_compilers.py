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
                    "action": {"type": "allow|block|warn|log_only|modify_args|redirect_tool"},
                },
                "confidence": 0.0,
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
    def __init__(
        self,
        inventory: Inventory,
        *,
        translator: AITranslator,
        min_confidence: float = 0.85,
    ) -> None:
        self.inventory = inventory
        self.translator = translator
        self.min_confidence = min_confidence

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

        confidence = float(payload.get("confidence") or 0.0)
        if confidence < self.min_confidence:
            return PolicyCompileResult(
                policy_id=document.id,
                compile_status=CompileStatus.NEEDS_REVIEW,
                confidence=confidence,
                compiled_policy=policy,
                message=payload.get("message")
                or f"AI confidence below threshold {self.min_confidence}",
                missing_fields=payload.get("missing_fields") or [],
            )
        return PolicyCompileResult(
            policy_id=document.id,
            compile_status=CompileStatus.COMPILED,
            confidence=confidence,
            compiled_policy=policy.model_copy(update={"policy_type": PolicyType.STRUCTURED}),
            message=payload.get("message"),
            missing_fields=payload.get("missing_fields") or [],
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
        if ai_result.compile_status == CompileStatus.NEEDS_REVIEW:
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
        min_confidence=float(ai_settings.get("require_review_below_confidence", 0.85)),
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
