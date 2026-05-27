"""Loan desk tools for the agentic policy demo."""

from __future__ import annotations

from openagentpolicy import policy_tool


@policy_tool(
    id="approve_loan",
    name="Approve Loan",
    description="Approve a loan application",
    risk_level="high",
    side_effect=True,
)
def approve_loan(
    application_id: str,
    approved_amount: float,
    approval_mode: str,
) -> dict[str, object]:
    return {
        "status": "approved",
        "application_id": application_id,
        "approved_amount": approved_amount,
        "approval_mode": approval_mode,
    }


@policy_tool(
    id="send_to_human_review",
    name="Send to Human Review",
    description="Escalate a loan application to a human reviewer",
    risk_level="medium",
    side_effect=True,
)
def send_to_human_review(application_id: str, reason: str) -> dict[str, object]:
    return {
        "status": "escalated",
        "application_id": application_id,
        "reason": reason,
    }
