from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PolicyType(str, Enum):
    STRUCTURED = "structured"
    ENGLISH = "english"


class CompileStatus(str, Enum):
    COMPILED = "compiled"
    NOT_ENFORCEABLE = "not_enforceable"
    NEEDS_REVIEW = "needs_review"


class TriggerEvent(str, Enum):
    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"
    BEFORE_FINAL_RESPONSE = "before_final_response"


class ConditionOperator(str, Enum):
    EQ = "=="
    NE = "!="
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"


class ActionType(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    WARN = "warn"
    LOG_ONLY = "log_only"
    MODIFY_ARGS = "modify_args"
    REDIRECT_TOOL = "redirect_tool"


class PolicyTrigger(BaseModel):
    event: TriggerEvent
    tool_id: str | None = None
    agent_id: str | None = None


class Condition(BaseModel):
    """Leaf condition or nested all/any/not group."""

    model_config = ConfigDict(populate_by_name=True)

    field: str | None = None
    operator: ConditionOperator | None = None
    value: Any | None = None
    all: list[Condition] | None = None
    any: list[Condition] | None = None
    not_: Condition | None = Field(default=None, alias="not")

    @model_validator(mode="after")
    def validate_shape(self) -> Condition:
        is_leaf = self.field is not None
        is_group = (
            self.all is not None
            or self.any is not None
            or self.not_ is not None
        )
        if is_leaf and is_group:
            raise ValueError("Condition cannot be both a leaf and a group")
        if not is_leaf and not is_group:
            raise ValueError(
                "Condition must be a leaf (field) or a group (all/any/not)"
            )
        if is_leaf and self.operator is None:
            raise ValueError("Leaf conditions require operator")
        return self

    @property
    def is_leaf(self) -> bool:
        return self.field is not None


class PolicyAction(BaseModel):
    type: ActionType
    message: str | None = None
    set: dict[str, Any] | None = None
    target_tool: str | None = None
    args: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> PolicyAction:
        if self.type == ActionType.MODIFY_ARGS and not self.set:
            raise ValueError("modify_args action requires set")
        if self.type == ActionType.REDIRECT_TOOL:
            if not self.target_tool:
                raise ValueError("redirect_tool action requires target_tool")
        return self


class Policy(BaseModel):
    id: str
    name: str | None = None
    enabled: bool = True
    policy_type: PolicyType = PolicyType.STRUCTURED
    trigger: PolicyTrigger | None = None
    conditions: Condition | None = None
    action: PolicyAction | None = None
    policy_text: str | None = None

    @model_validator(mode="after")
    def validate_policy_shape(self) -> Policy:
        if self.policy_type == PolicyType.ENGLISH:
            return self
        if self.trigger is None:
            raise ValueError("structured policies require trigger")
        if self.action is None:
            raise ValueError("structured policies require action")
        return self


class PolicyCompileResult(BaseModel):
    policy_id: str
    compile_status: CompileStatus
    confidence: float = 0.0
    resolved_terms: dict[str, str] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    compiled_policy: Policy | None = None
    message: str | None = None


class PolicyDocument(BaseModel):
    """Load-time document: accepts Policy fields, English text, or legacy rules."""

    id: str
    name: str | None = None
    description: str | None = None
    enabled: bool = True
    policy_type: PolicyType = PolicyType.STRUCTURED
    trigger: PolicyTrigger | None = None
    conditions: Condition | None = None
    action: PolicyAction | None = None
    english: str | None = None
    policy_text: str | None = None
    hints: dict[str, Any] | None = None
    rules: list["PolicyRule"] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_english_field(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("english") and not data.get("policy_text"):
            data = dict(data)
            data.setdefault("policy_text", data["english"])
        return data

    @model_validator(mode="after")
    def validate_document_shape(self) -> PolicyDocument:
        if self.policy_type == PolicyType.ENGLISH:
            if not self.english_text:
                raise ValueError("english policies require english or policy_text")
            return self
        if self.rules:
            return self
        return self

    @property
    def english_text(self) -> str | None:
        return (self.english or self.policy_text or "").strip() or None

    def to_policy(self) -> Policy:
        if self.rules:
            raise ValueError(
                "legacy rules must be compiled before converting to Policy"
            )
        return Policy(
            id=self.id,
            name=self.name,
            enabled=self.enabled,
            policy_type=self.policy_type,
            trigger=self.trigger,
            conditions=self.conditions,
            action=self.action,
            policy_text=self.english_text,
        )


# Legacy models used by compiler/evaluator adapters (deprecated)
class PolicyRule(BaseModel):
    id: str
    tool: str
    effect: str = "deny"
    reason: str = ""
    conditions: dict[str, object] = Field(default_factory=dict)


class CompiledPolicy(BaseModel):
    id: str
    name: str | None = None
    rules: list[PolicyRule] = Field(default_factory=list)
