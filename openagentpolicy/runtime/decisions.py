from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DecisionType(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    WARN = "warn"
    LOG_ONLY = "log_only"
    MODIFY_ARGS = "modify_args"
    REDIRECT_TOOL = "redirect_tool"


class PolicyDecision(BaseModel):
    decision: DecisionType
    matched_policies: list[str] = Field(default_factory=list)
    message: str | None = None
    modified_args: dict[str, object] | None = None
    target_tool: str | None = None
    target_args: dict[str, object] | None = None


# Backward-compatible aliases
Decision = DecisionType
DecisionResult = PolicyDecision

# Legacy deny maps to block
DENY = DecisionType.BLOCK
