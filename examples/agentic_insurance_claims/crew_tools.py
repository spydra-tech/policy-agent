"""CrewAI tools that delegate to @policy_tool functions under agent_session.

Each tool is bound to a crew member's agent_id so openagentpolicy sees the correct
identity when the LLM invokes a tool.
"""

from __future__ import annotations

import json
from typing import Any, Type

from pydantic import BaseModel, Field

from agent_session import run_as_agent
from tools import (
    flag_fraud_signal,
    issue_claim_payout,
    lookup_policy,
    record_claim_intake,
)

try:
    from crewai.tools import BaseTool
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "crewai is required. Install with: pip install -r requirements.txt"
    ) from exc


def _json_result(payload: Any) -> str:
    return json.dumps(payload, default=str)


class _PolicyIdInput(BaseModel):
    policy_id: str = Field(..., description="Policy identifier, e.g. POL-8812")


class _ClaimIntakeInput(BaseModel):
    claim_id: str = Field(..., description="Claim identifier")
    amount: float = Field(..., description="Claim amount in USD")
    loss_type: str = Field(
        ...,
        description="Loss type: auto_collision, property_damage, or total_loss",
    )


class _ClaimReasonInput(BaseModel):
    claim_id: str = Field(..., description="Claim identifier")
    reason: str = Field(..., description="Reason for the fraud flag")


class _PayoutInput(BaseModel):
    claim_id: str = Field(..., description="Claim identifier")
    amount: float = Field(..., description="Payout amount in USD")
    loss_type: str | None = Field(
        default=None,
        description="Loss type: auto_collision, property_damage, or total_loss",
    )


def _tool_class(
    *,
    name: str,
    description: str,
    args_schema: Type[BaseModel],
    agent_id: str,
    fn: Any,
) -> type[BaseTool]:
    """Build a CrewAI BaseTool subclass bound to one openagentpolicy agent."""

    class _BoundTool(BaseTool):  # type: ignore[misc]
        name: str = name
        description: str = description
        args_schema: Type[BaseModel] = args_schema
        _agent_id: str = agent_id
        _fn: Any = fn

        def _run(self, **kwargs: Any) -> str:
            result = run_as_agent(self._agent_id, self._fn, **kwargs)
            return _json_result(result)

    _BoundTool.__name__ = f"{name.replace(' ', '')}Tool"
    return _BoundTool


def tools_for_adjuster() -> list[BaseTool]:
    return [
        _tool_class(
            name="lookup_policy",
            description="Look up policy coverage for a policy id",
            args_schema=_PolicyIdInput,
            agent_id="claims-adjuster-agent",
            fn=lookup_policy,
        )(),
        _tool_class(
            name="record_claim_intake",
            description="Record a new claim intake with amount and loss type",
            args_schema=_ClaimIntakeInput,
            agent_id="claims-adjuster-agent",
            fn=record_claim_intake,
        )(),
    ]


def tools_for_fraud_analyst() -> list[BaseTool]:
    return [
        _tool_class(
            name="flag_fraud_signal",
            description="Flag a claim for fraud review",
            args_schema=_ClaimReasonInput,
            agent_id="fraud-analyst-agent",
            fn=flag_fraud_signal,
        )(),
    ]


def tools_for_payout_agent() -> list[BaseTool]:
    return [
        _tool_class(
            name="issue_claim_payout",
            description="Issue a payout on a claim",
            args_schema=_PayoutInput,
            agent_id="payout-agent",
            fn=issue_claim_payout,
        )(),
    ]
