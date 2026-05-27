"""Loan approval demo for openagentpolicy."""

from __future__ import annotations

from pathlib import Path

from openagentpolicy import configure, policy_tool
from openagentpolicy.annotations import PolicyViolation

EXAMPLE_DIR = Path(__file__).parent

configure(EXAMPLE_DIR / "openagentpolicy.yaml")


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


def _run_approve_loan(
    label: str,
    *,
    application_id: str,
    approved_amount: float,
    approval_mode: str,
) -> None:
    print(f"\n--- {label} ---")
    print(
        f"approve_loan(application_id={application_id!r}, "
        f"approved_amount={approved_amount}, approval_mode={approval_mode!r})"
    )
    try:
        result = approve_loan(
            application_id=application_id,
            approved_amount=approved_amount,
            approval_mode=approval_mode,
        )
        print(f"Result: ALLOWED")
        print(f"  {result}")
    except PolicyViolation as exc:
        print(f"Result: BLOCKED")
        print(f"  {exc}")
        if exc.decision:
            print(f"  decision={exc.decision.decision.value}")
            if exc.decision.message:
                print(f"  message={exc.decision.message!r}")


def main() -> None:
    print("openagentpolicy loan approval example")
    print(f"Config: {EXAMPLE_DIR / 'openagentpolicy.yaml'}")
    print("Active policy: policies/auto_approval_structured.yaml")
    print("(Set enabled: true on auto_approval_english.yaml to use English policy instead)")

    _run_approve_loan(
        "Small auto loan (expected: allowed)",
        application_id="app-1001",
        approved_amount=4000,
        approval_mode="auto",
    )
    _run_approve_loan(
        "Large auto loan (expected: blocked)",
        application_id="app-1002",
        approved_amount=7500,
        approval_mode="auto",
    )

    print("\n--- Trace recording ---")
    traces_file = EXAMPLE_DIR / "openagentpolicy_traces" / "events.jsonl"
    if traces_file.exists():
        lines = [
            line for line in traces_file.read_text().splitlines() if line.strip()
        ]
        print(f"Trace events written to: {traces_file}")
        print(f"Event count: {len(lines)}")
    else:
        print(f"No trace file yet at: {traces_file}")

    print("\nGenerate inventory from traces:")
    print(
        "  openagentpolicy generate-inventory \\\n"
        f"    --traces {traces_file} \\\n"
        f"    --output {EXAMPLE_DIR / 'generated_inventory.yaml'}"
    )


if __name__ == "__main__":
    main()
