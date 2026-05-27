from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from openagentpolicy.runtime.decisions import DecisionType


class PolicyEvent(BaseModel):
    event_type: str
    application_id: str | None = None
    agent_id: str | None = None
    tool_id: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    tool_result: dict[str, Any] | None = None
    final_response: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    decision: DecisionType | None = None
    message: str | None = None
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
