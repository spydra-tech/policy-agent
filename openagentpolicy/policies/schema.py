from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PolicyType(str, Enum):
    STRUCTURED = "structured"
    ENGLISH = "english"
    COMPILED = "compiled"


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
    REGEX = "regex"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"


class ActionType(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    WARN = "warn"
    LOG_ONLY = "log_only"
    REDACT_RESULT = "redact_result"
    ESCALATE = "escalate"
    MODIFY_ARGS = "modify_args"


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
    case_sensitive: bool = False
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

    @model_validator(mode="after")
    def validate_action_fields(self) -> PolicyAction:
        if self.type == ActionType.MODIFY_ARGS and not self.set:
            raise ValueError("modify_args action requires set")
        return self


class Policy(BaseModel):
    id: str
    name: str | None = None
    enabled: bool = True
    policy_type: PolicyType = PolicyType.STRUCTURED
    trigger: PolicyTrigger | None = None
    conditions: Condition | None = None
    action: PolicyAction | None = None
    english: str | None = None
    source: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_policy_shape(self) -> Policy:
        if self.policy_type == PolicyType.ENGLISH:
            if not (self.english or "").strip():
                raise ValueError("english policies require english text")
            if self.trigger is not None or self.conditions is not None or self.action is not None:
                raise ValueError(
                    "english policies cannot define trigger/conditions/action"
                )
            return self
        if self.policy_type in {PolicyType.STRUCTURED, PolicyType.COMPILED} and self.english:
            raise ValueError("structured/compiled policies cannot include english text")
        if self.trigger is None:
            raise ValueError("structured/compiled policies require trigger")
        if self.conditions is None:
            raise ValueError("structured/compiled policies require conditions")
        if self.action is None:
            raise ValueError("structured/compiled policies require action")
        if self.policy_type == PolicyType.COMPILED:
            if not self.source:
                raise ValueError("compiled policies require source metadata")
            if not self.validation:
                raise ValueError("compiled policies require validation metadata")
            if self.validation.get("enforceability") != "enforceable":
                raise ValueError(
                    "compiled policies require validation.enforceability=enforceable"
                )
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
    """Load-time document: accepts structured Policy fields or English text."""

    id: str
    name: str | None = None
    description: str | None = None
    enabled: bool = True
    policy_type: PolicyType = PolicyType.STRUCTURED
    trigger: PolicyTrigger | None = None
    conditions: Condition | None = None
    action: PolicyAction | None = None
    english: str | None = None
    source: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    hints: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_document_shape(self) -> PolicyDocument:
        if self.policy_type == PolicyType.ENGLISH:
            if not self.english_text:
                raise ValueError("english policies require english")
            if self.trigger is not None or self.conditions is not None or self.action is not None:
                raise ValueError(
                    "english policies cannot define trigger/conditions/action"
                )
            return self
        if self.policy_type in {PolicyType.STRUCTURED, PolicyType.COMPILED} and self.english:
            raise ValueError("structured/compiled policies cannot include english text")
        if self.trigger is None:
            raise ValueError("structured/compiled policies require trigger")
        if self.conditions is None:
            raise ValueError("structured/compiled policies require conditions")
        if self.action is None:
            raise ValueError("structured/compiled policies require action")
        return self

    @property
    def english_text(self) -> str | None:
        return (self.english or "").strip() or None

    def to_policy(self) -> Policy:
        return Policy(
            id=self.id,
            name=self.name,
            enabled=self.enabled,
            policy_type=self.policy_type,
            trigger=self.trigger,
            conditions=self.conditions,
            action=self.action,
            english=self.english_text,
            source=self.source,
            validation=self.validation,
        )
