"""Insurance claims tools for the CrewAI policy demo (mock claims system)."""

from __future__ import annotations

from openagentpolicy import policy_tool

_MOCK_POLICIES: dict[str, dict[str, object]] = {
    "POL-8812": {
        "policy_id": "POL-8812",
        "holder": "Jordan Lee",
        "coverage": "comprehensive_auto",
        "deductible": 500,
    },
}

_CLAIMS: dict[str, dict[str, object]] = {}


@policy_tool(
    id="lookup_policy",
    name="Lookup Policy",
    description="Retrieve policy coverage details",
    risk_level="low",
    side_effect=False,
)
def lookup_policy(policy_id: str) -> dict[str, object]:
    return _MOCK_POLICIES.get(
        policy_id,
        {"policy_id": policy_id, "holder": "Unknown", "coverage": "unknown"},
    )


@policy_tool(
    id="record_claim_intake",
    name="Record Claim Intake",
    description="Register a new claim",
    risk_level="medium",
    side_effect=True,
)
def record_claim_intake(claim_id: str, amount: float, loss_type: str) -> dict[str, object]:
    record = {
        "status": "intake_recorded",
        "claim_id": claim_id,
        "amount": amount,
        "loss_type": loss_type,
    }
    _CLAIMS[claim_id] = record
    return record


@policy_tool(
    id="flag_fraud_signal",
    name="Flag Fraud Signal",
    description="Add a fraud review flag",
    risk_level="medium",
    side_effect=True,
)
def flag_fraud_signal(claim_id: str, reason: str) -> dict[str, object]:
    claim = _CLAIMS.setdefault(claim_id, {"claim_id": claim_id})
    claim["fraud_flag"] = True
    claim["fraud_reason"] = reason
    return {"status": "flagged", "claim_id": claim_id, "reason": reason}


@policy_tool(
    id="issue_claim_payout",
    name="Issue Claim Payout",
    description="Issue payment on a claim",
    risk_level="high",
    side_effect=True,
)
def issue_claim_payout(
    claim_id: str,
    amount: float,
    loss_type: str | None = None,
) -> dict[str, object]:
    claim = _CLAIMS.get(claim_id, {})
    resolved_loss = loss_type or claim.get("loss_type")
    return {
        "status": "payout_issued",
        "claim_id": claim_id,
        "amount": amount,
        "loss_type": resolved_loss,
        "payment_ref": f"PAY-{claim_id}",
    }
