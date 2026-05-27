from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from openagentpolicy.inventory.schema import Inventory, Tool
from openagentpolicy.policies.schema import (
    ActionType,
    CompileStatus,
    Condition,
    ConditionOperator,
    Policy,
    PolicyAction,
    PolicyCompileResult,
    PolicyDocument,
    PolicyRule,
    PolicyTrigger,
    PolicyType,
    TriggerEvent,
)

COMPARISON_PATTERNS: list[tuple[re.Pattern[str], ConditionOperator]] = [
    (
        re.compile(
            r"if\s+(?P<field>[a-z][a-z0-9\s_]*?)\s+is\s+"
            r"(?:greater than|more than|above)\s+"
            r"(?P<value>[\d.]+)",
            re.IGNORECASE,
        ),
        ConditionOperator.GT,
    ),
    (
        re.compile(
            r"(?P<field>[a-z][a-z0-9\s_]*?)\s+is\s+"
            r"(?:greater than|more than|above)\s+"
            r"(?P<value>[\d.]+)",
            re.IGNORECASE,
        ),
        ConditionOperator.GT,
    ),
    (
        re.compile(
            r"(?P<field>[a-z][a-z0-9\s_]*?)\s+is\s+"
            r"(?:less than|below)\s+"
            r"(?P<value>[\d.]+)",
            re.IGNORECASE,
        ),
        ConditionOperator.LT,
    ),
    (
        re.compile(
            r"(?P<field>[a-z][a-z0-9\s_]*?)\s+is\s+equal to\s+"
            r"(?P<value>[\d.]+)",
            re.IGNORECASE,
        ),
        ConditionOperator.EQ,
    ),
]

MISSING_FIELD_PATTERN = re.compile(
    r"if\s+(?P<field>[a-z][a-z0-9\s_]+?)\s+is\s+missing",
    re.IGNORECASE,
)

NOT_ALLOWED_PHRASES = (
    "not allowed",
    "is not allowed",
    "are not allowed",
    "not permitted",
    "is not permitted",
    "may not",
    "cannot",
    "can't",
)

AGENT_ONLY_PATTERN = re.compile(
    r"only\s+(?P<agent>[a-z][a-z0-9\s_-]+?)\s+may\s+(?:call|use)\s+"
    r"(?P<tool>[a-z][a-z0-9\s_-]+)",
    re.IGNORECASE,
)


@dataclass
class _FieldBinding:
    tool_id: str
    field_path: str
    argument_name: str


@dataclass
class _ValueBinding:
    tool_id: str
    field_path: str
    argument_name: str
    value: Any
    phrase: str


@dataclass
class InventoryIndex:
    """Phrase index built from inventory for English compilation."""

    field_phrases: dict[str, _FieldBinding] = field(default_factory=dict)
    value_phrases: dict[str, _ValueBinding] = field(default_factory=dict)

    @classmethod
    def from_inventory(cls, inventory: Inventory) -> InventoryIndex:
        index = cls()
        for tool in inventory.tools:
            index._index_tool(tool)
        return index

    def _index_tool(self, tool: Tool) -> None:
        for arg_name, schema in tool.arguments.items():
            field_path = f"tool_args.{arg_name}"
            phrases = {
                _normalize_phrase(arg_name.replace("_", " ")),
                _normalize_phrase(arg_name),
            }
            if schema.description:
                phrases.add(_normalize_phrase(schema.description))
            if schema.aliases:
                for alias in schema.aliases:
                    phrases.add(_normalize_phrase(alias))
            for phrase in phrases:
                if phrase:
                    index_entry = _FieldBinding(
                        tool_id=tool.id,
                        field_path=field_path,
                        argument_name=arg_name,
                    )
                    existing = self.field_phrases.get(phrase)
                    if existing and existing.tool_id != tool.id:
                        continue
                    self.field_phrases[phrase] = index_entry

            if schema.allowed_values:
                for value in schema.allowed_values:
                    value_phrases = _value_phrases_for(
                        arg_name, value, tool, schema.aliases
                    )
                    for phrase in value_phrases:
                        self.value_phrases[phrase] = _ValueBinding(
                            tool_id=tool.id,
                            field_path=field_path,
                            argument_name=arg_name,
                            value=value,
                            phrase=phrase,
                        )


def _value_phrases_for(
    arg_name: str,
    value: Any,
    tool: Tool,
    aliases: list[str] | None,
) -> set[str]:
    phrases: set[str] = set()
    value_text = str(value).lower()
    if arg_name == "approval_mode" and value_text == "auto":
        phrases.update(
            {
                "auto approval",
                "auto approve",
                "automatic approval",
            }
        )
    phrases.add(f"{value_text} {arg_name.replace('_', ' ')}")
    phrases.add(value_text)
    if tool.name:
        phrases.add(f"{value_text} {tool.name.lower()}")
    if aliases:
        for alias in aliases:
            phrases.add(f"{value_text} {_normalize_phrase(alias)}")
    return {p for p in phrases if p}


def _normalize_phrase(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _clean_field_phrase(phrase: str) -> str:
    return re.sub(r"^if\s+", "", phrase.strip(), flags=re.IGNORECASE)


class PolicyCompiler:
    """Rule-based compiler for English policies into structured policies."""

    def __init__(self, inventory: Inventory | None = None) -> None:
        self.inventory = inventory or Inventory()
        self._index = InventoryIndex.from_inventory(self.inventory)

    def with_inventory(self, inventory: Inventory) -> PolicyCompiler:
        return PolicyCompiler(inventory)

    def compile_document(self, document: PolicyDocument) -> PolicyCompileResult:
        if document.rules:
            policies = [self._rule_to_policy(document, rule) for rule in document.rules]
            if len(policies) == 1:
                return PolicyCompileResult(
                    policy_id=document.id,
                    compile_status=CompileStatus.COMPILED,
                    confidence=1.0,
                    compiled_policy=policies[0],
                )
            return PolicyCompileResult(
                policy_id=document.id,
                compile_status=CompileStatus.NEEDS_REVIEW,
                confidence=0.5,
                message="Legacy multi-rule documents require review",
            )

        if document.policy_type == PolicyType.ENGLISH or document.english_text:
            return self._compile_english_document(document)

        try:
            policy = document.to_policy()
            if policy.policy_type == PolicyType.STRUCTURED:
                return PolicyCompileResult(
                    policy_id=document.id,
                    compile_status=CompileStatus.COMPILED,
                    confidence=1.0,
                    compiled_policy=policy,
                )
        except ValueError as exc:
            return PolicyCompileResult(
                policy_id=document.id,
                compile_status=CompileStatus.NOT_ENFORCEABLE,
                confidence=0.0,
                message=str(exc),
            )

        return PolicyCompileResult(
            policy_id=document.id,
            compile_status=CompileStatus.NOT_ENFORCEABLE,
            confidence=0.0,
            message="Unsupported policy document",
        )

    def compile(self, document: PolicyDocument) -> list[Policy]:
        result = self.compile_document(document)
        if result.compile_status == CompileStatus.COMPILED and result.compiled_policy:
            return [result.compiled_policy]
        return []

    def compile_all(
        self, documents: list[PolicyDocument]
    ) -> list[PolicyCompileResult]:
        return [self.compile_document(document) for document in documents]

    def _compile_english_document(self, document: PolicyDocument) -> PolicyCompileResult:
        text = document.english_text or ""
        normalized = _normalize_phrase(text)

        agent_only = self._try_compile_agent_only(document, normalized)
        if agent_only is not None:
            return agent_only

        missing_fields: list[str] = []
        resolved_terms: dict[str, str] = {}
        conditions: list[Condition] = []
        tools_involved: set[str] = set()

        seen_conditions: set[tuple[str, str, str]] = set()

        for pattern, operator in COMPARISON_PATTERNS:
            for match in pattern.finditer(normalized):
                field_phrase = _clean_field_phrase(match.group("field"))
                raw_value = match.group("value")
                binding = self._resolve_field_phrase(field_phrase, missing_fields)
                if binding is None:
                    continue
                key = (binding.field_path, operator.value, raw_value)
                if key in seen_conditions:
                    continue
                seen_conditions.add(key)
                tools_involved.add(binding.tool_id)
                resolved_terms[field_phrase] = binding.field_path
                conditions.append(
                    Condition(
                        field=binding.field_path,
                        operator=operator,
                        value=_parse_number(raw_value),
                    )
                )

        for match in MISSING_FIELD_PATTERN.finditer(normalized):
            field_phrase = _clean_field_phrase(match.group("field"))
            binding = self._resolve_field_phrase(field_phrase, missing_fields)
            if binding is None:
                continue
            key = (binding.field_path, ConditionOperator.NOT_EXISTS.value, "")
            if key in seen_conditions:
                continue
            seen_conditions.add(key)
            tools_involved.add(binding.tool_id)
            resolved_terms[field_phrase] = binding.field_path
            conditions.append(
                Condition(
                    field=binding.field_path,
                    operator=ConditionOperator.NOT_EXISTS,
                )
            )

        for phrase, binding in sorted(
            self._index.value_phrases.items(), key=lambda x: -len(x[0])
        ):
            if " " not in phrase:
                continue
            if phrase in normalized:
                key = (
                    binding.field_path,
                    ConditionOperator.EQ.value,
                    str(binding.value),
                )
                if key in seen_conditions:
                    continue
                seen_conditions.add(key)
                tools_involved.add(binding.tool_id)
                resolved_terms[phrase] = (
                    f"{binding.field_path} {ConditionOperator.EQ.value} {binding.value!r}"
                )
                conditions.append(
                    Condition(
                        field=binding.field_path,
                        operator=ConditionOperator.EQ,
                        value=binding.value,
                    )
                )

        if missing_fields:
            return PolicyCompileResult(
                policy_id=document.id,
                compile_status=CompileStatus.NOT_ENFORCEABLE,
                confidence=0.0,
                resolved_terms=resolved_terms,
                missing_fields=sorted(set(missing_fields)),
                message="Could not resolve all fields from inventory",
            )

        if not conditions:
            return PolicyCompileResult(
                policy_id=document.id,
                compile_status=CompileStatus.NOT_ENFORCEABLE,
                confidence=0.0,
                resolved_terms=resolved_terms,
                message="No enforceable conditions detected in English policy",
            )

        if len(tools_involved) > 1:
            return PolicyCompileResult(
                policy_id=document.id,
                compile_status=CompileStatus.NOT_ENFORCEABLE,
                confidence=0.3,
                resolved_terms=resolved_terms,
                message=f"Resolved fields span multiple tools: {sorted(tools_involved)}",
            )

        tool_id = next(iter(tools_involved)) if tools_involved else None
        action = self._resolve_action(document, normalized)
        if action is None:
            return PolicyCompileResult(
                policy_id=document.id,
                compile_status=CompileStatus.NOT_ENFORCEABLE,
                confidence=0.4,
                resolved_terms=resolved_terms,
                message="Could not determine policy action",
            )

        condition_tree = conditions[0] if len(conditions) == 1 else Condition(all=conditions)
        confidence = _score_confidence(conditions, resolved_terms, missing_fields)

        compiled = Policy(
            id=document.id,
            name=document.name,
            enabled=document.enabled,
            policy_type=PolicyType.STRUCTURED,
            trigger=PolicyTrigger(
                event=TriggerEvent.BEFORE_TOOL_CALL,
                tool_id=tool_id,
            ),
            conditions=condition_tree,
            action=action,
        )
        return PolicyCompileResult(
            policy_id=document.id,
            compile_status=CompileStatus.COMPILED,
            confidence=confidence,
            resolved_terms=resolved_terms,
            missing_fields=missing_fields,
            compiled_policy=compiled,
        )

    def _try_compile_agent_only(
        self, document: PolicyDocument, normalized: str
    ) -> PolicyCompileResult | None:
        match = AGENT_ONLY_PATTERN.search(normalized)
        if match is None:
            return None

        agent_phrase = _normalize_phrase(match.group("agent"))
        tool_phrase = _normalize_phrase(match.group("tool"))
        allowed_agent = self._resolve_agent_id(agent_phrase)
        tool_id = self._resolve_tool_id(tool_phrase)

        if allowed_agent is None or tool_id is None:
            missing: list[str] = []
            if allowed_agent is None:
                missing.append(agent_phrase)
            if tool_id is None:
                missing.append(tool_phrase)
            return PolicyCompileResult(
                policy_id=document.id,
                compile_status=CompileStatus.NOT_ENFORCEABLE,
                confidence=0.0,
                missing_fields=missing,
                message="Could not resolve agent or tool from inventory for allowlist policy",
            )

        action = self._resolve_action(document, normalized)
        if action is None:
            action = PolicyAction(
                type=ActionType.BLOCK,
                message=document.name or "Agent is not allowed to call this tool",
            )

        compiled = Policy(
            id=document.id,
            name=document.name,
            enabled=document.enabled,
            policy_type=PolicyType.STRUCTURED,
            trigger=PolicyTrigger(
                event=TriggerEvent.BEFORE_TOOL_CALL,
                tool_id=tool_id,
            ),
            conditions=Condition(
                field="agent_id",
                operator=ConditionOperator.NE,
                value=allowed_agent,
            ),
            action=action,
        )
        return PolicyCompileResult(
            policy_id=document.id,
            compile_status=CompileStatus.COMPILED,
            confidence=0.9,
            resolved_terms={
                agent_phrase: allowed_agent,
                tool_phrase: tool_id,
            },
            compiled_policy=compiled,
        )

    def _resolve_agent_id(self, phrase: str) -> str | None:
        normalized = _normalize_phrase(phrase)
        for agent in self.inventory.agents:
            candidates = {
                _normalize_phrase(agent.id),
                _normalize_phrase(agent.id.replace("-", " ")),
                _normalize_phrase(agent.id.replace("_", " ")),
            }
            if agent.name:
                candidates.add(_normalize_phrase(agent.name))
            if normalized in candidates:
                return agent.id
        return None

    def _resolve_tool_id(self, phrase: str) -> str | None:
        normalized = _normalize_phrase(phrase)
        for tool in self.inventory.tools:
            candidates = {
                _normalize_phrase(tool.id),
                _normalize_phrase(tool.id.replace("_", " ")),
            }
            if tool.name:
                candidates.add(_normalize_phrase(tool.name))
            if normalized in candidates:
                return tool.id
        return None

    def _resolve_field_phrase(
        self, phrase: str, missing_fields: list[str]
    ) -> _FieldBinding | None:
        normalized = _normalize_phrase(phrase)
        binding = self._index.field_phrases.get(normalized)
        if binding is not None:
            return binding
        missing_fields.append(phrase)
        return None

    def _resolve_action(
        self, document: PolicyDocument, normalized_text: str
    ) -> PolicyAction | None:
        if document.hints and "action" in document.hints:
            return PolicyAction.model_validate(document.hints["action"])

        if any(phrase in normalized_text for phrase in NOT_ALLOWED_PHRASES):
            return PolicyAction(
                type=ActionType.BLOCK,
                message=document.name or "Policy violation",
            )

        if "warn" in normalized_text:
            return PolicyAction(type=ActionType.WARN, message=document.name)

        return None

    def _rule_to_policy(self, document: PolicyDocument, rule: PolicyRule) -> Policy:
        conditions = self._legacy_conditions_to_tree(rule.conditions)
        effect = rule.effect
        action_type = (
            ActionType.BLOCK
            if effect in {"deny", "block"}
            else ActionType.ALLOW
        )
        return Policy(
            id=rule.id,
            name=document.name,
            enabled=document.enabled,
            policy_type=PolicyType.STRUCTURED,
            trigger=PolicyTrigger(
                event=TriggerEvent.BEFORE_TOOL_CALL,
                tool_id=rule.tool,
            ),
            conditions=conditions,
            action=PolicyAction(type=action_type, message=rule.reason),
        )

    def _legacy_conditions_to_tree(
        self, conditions: dict[str, object]
    ) -> Condition | None:
        if not conditions:
            return None
        leaves: list[Condition] = []
        for key, expected in conditions.items():
            field_path = key if key.startswith("tool_args.") else f"tool_args.{key}"
            if isinstance(expected, dict):
                for op_key, value in expected.items():
                    operator = {
                        "gt": ConditionOperator.GT,
                        "gte": ConditionOperator.GTE,
                        "lt": ConditionOperator.LT,
                        "lte": ConditionOperator.LTE,
                        "eq": ConditionOperator.EQ,
                    }.get(op_key, ConditionOperator.EQ)
                    leaves.append(
                        Condition(
                            field=field_path,
                            operator=operator,
                            value=value,
                        )
                    )
            else:
                leaves.append(
                    Condition(
                        field=field_path,
                        operator=ConditionOperator.EQ,
                        value=expected,
                    )
                )
        if len(leaves) == 1:
            return leaves[0]
        return Condition(all=leaves)


def _parse_number(raw: str) -> float | int:
    if "." in raw:
        return float(raw)
    return int(raw)


def _score_confidence(
    conditions: list[Condition],
    resolved_terms: dict[str, str],
    missing_fields: list[str],
) -> float:
    if missing_fields:
        return 0.0
    base = 0.65
    base += min(0.2, 0.1 * len(conditions))
    base += min(0.15, 0.05 * len(resolved_terms))
    return min(base, 0.95)
