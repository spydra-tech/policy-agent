from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from openagentpolicy.policies.schema import Policy


class CompileResultStatus(str, Enum):
    COMPILED = "compiled"
    NOT_ENFORCEABLE = "not_enforceable"
    NEEDS_REVIEW = "needs_review"
    ERROR = "error"


class Enforceability(str, Enum):
    ENFORCEABLE = "enforceable"
    NOT_ENFORCEABLE = "not_enforceable"
    NEEDS_REVIEW = "needs_review"


class CompileError(BaseModel):
    code: str
    message: str


class CompilerMetadata(BaseModel):
    compiler_type: str = "rule_based"
    compiler_version: str = "1.0"
    inventory_version: str | None = None
    compiled_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class CompileResult(BaseModel):
    status: CompileResultStatus
    policy_id: str
    english: str
    compiled_policy: Policy | None = None
    resolved_terms: dict[str, str] = Field(default_factory=dict)
    missing_terms: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    errors: list[CompileError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    test_cases: list[dict[str, Any]] = Field(default_factory=list)
    enforceability: Enforceability
    compiler_metadata: CompilerMetadata = Field(default_factory=CompilerMetadata)
    suggested_fixes: list[str] = Field(default_factory=list)
