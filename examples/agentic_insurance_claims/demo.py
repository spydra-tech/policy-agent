#!/usr/bin/env python3
"""Insurance claims demo: CrewAI roles + openagentpolicy enforcement.

Primary path: scripted crew workflow (no LLM). Optional: real CrewAI kickoff when
OPENAI_API_KEY is set — see ``python demo.py --crew``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

from openagentpolicy import configure
from openagentpolicy.annotations import PolicyViolation
from openagentpolicy.cli.validate import compile_policy_file

from agent_session import finalize_response, run_as_agent, run_crew_role
from tools import (
    flag_fraud_signal,
    issue_claim_payout,
    lookup_policy,
    record_claim_intake,
)

EXAMPLE_DIR = Path(__file__).parent
INVENTORY = EXAMPLE_DIR / "inventory.yaml"
POLICIES = EXAMPLE_DIR / "policies"
CONFIG = EXAMPLE_DIR / "openagentpolicy.yaml"

CLAIM_ID = "CLM-9001"
POLICY_ID = "POL-8812"


def _header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print("=" * 60)


def _show_compile(path: Path) -> None:
    for result in compile_policy_file(path, INVENTORY):
        print(f"  {path.name}: {result.get('compile_status')}")


def _run_tool(
    label: str,
    agent_id: str,
    fn: Callable[..., Any],
    /,
    *,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    print(f"\n--- {label} ---")
    print(f"  agent={agent_id!r}")
    if metadata:
        print(f"  metadata={metadata}")
    try:
        result = run_as_agent(agent_id, fn, metadata=metadata, **kwargs)
        print("  Result: ALLOWED")
        print(f"  {result}")
    except PolicyViolation as exc:
        print("  Result: BLOCKED")
        print(f"  {exc}")
        if exc.decision and exc.decision.matched_policies:
            print(f"  matched_policies={exc.decision.matched_policies}")


def _run_response(label: str, text: str) -> None:
    print(f"\n--- {label} ---")
    try:
        finalize_response(text, agent_id="claims-adjuster-agent")
        print("  Result: ALLOWED")
    except PolicyViolation as exc:
        print("  Result: BLOCKED")
        print(f"  {exc}")


def run_scripted_crew_workflow() -> None:
    """Simulate sequential crew tasks with explicit agent identities."""

    def adjuster_intake() -> dict[str, object]:
        lookup_policy(policy_id=POLICY_ID)
        return record_claim_intake(
            claim_id=CLAIM_ID,
            amount=12000,
            loss_type="auto_collision",
        )

    def fraud_review() -> dict[str, object]:
        return flag_fraud_signal(
            claim_id=CLAIM_ID,
            reason="velocity check on new policy",
        )

    def payout_attempt() -> dict[str, object]:
        return issue_claim_payout(claim_id=CLAIM_ID, amount=12000)

    _header("Crew step 1 — Claims Adjuster (intake)")
    try:
        out = run_crew_role("claims-adjuster-agent", adjuster_intake)
        print(f"  Result: ALLOWED\n  {out}")
    except PolicyViolation as exc:
        print(f"  Result: BLOCKED\n  {exc}")

    _header("Crew step 2 — Fraud Analyst (flag)")
    try:
        out = run_crew_role("fraud-analyst-agent", fraud_review)
        print(f"  Result: ALLOWED\n  {out}")
    except PolicyViolation as exc:
        print(f"  Result: BLOCKED\n  {exc}")

    _header("Crew step 3 — Payout Specialist (payment)")
    try:
        out = run_crew_role(
            "payout-agent",
            payout_attempt,
            metadata={"supervisor_approved": True},
        )
        print(f"  Result: ALLOWED\n  {out}")
    except PolicyViolation as exc:
        print(f"  Result: BLOCKED\n  {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Insurance claims policy demo")
    parser.add_argument(
        "--crew",
        action="store_true",
        help="Run real CrewAI kickoff (requires OPENAI_API_KEY and crewai)",
    )
    args = parser.parse_args()

    configure(CONFIG)

    _header("Phase 1 — English policy compilation")
    for name in (
        "01_block_large_total_loss_payout_english.yaml",
        "02_only_payout_agent_may_pay_english.yaml",
        "05_only_adjuster_may_intake_english.yaml",
    ):
        _show_compile(POLICIES / name)

    _header("Phase 2 — Crew-style intake (adjuster tools)")
    run_as_agent("claims-adjuster-agent", lookup_policy, policy_id=POLICY_ID)
    print("  lookup_policy: OK")
    _run_tool(
        "A: adjuster records $12k collision claim (expected: ALLOW)",
        "claims-adjuster-agent",
        record_claim_intake,
        claim_id=CLAIM_ID,
        amount=12000,
        loss_type="auto_collision",
    )
    _run_tool(
        "A2: customer-service tries intake (expected: BLOCK — only adjuster)",
        "customer-service-agent",
        record_claim_intake,
        claim_id="CLM-9002",
        amount=3000,
        loss_type="property_damage",
    )

    _header("Phase 3 — Payout policies")
    _run_tool(
        "B: fraud-analyst tries payout (expected: BLOCK — only payout-agent)",
        "fraud-analyst-agent",
        issue_claim_payout,
        claim_id=CLAIM_ID,
        amount=12000,
    )
    _run_tool(
        "C: payout-agent $20k total loss, no supervisor (expected: BLOCK — metadata)",
        "payout-agent",
        issue_claim_payout,
        claim_id="CLM-5500",
        amount=20000,
        metadata={"supervisor_approved": False},
    )
    run_as_agent(
        "claims-adjuster-agent",
        record_claim_intake,
        claim_id="CLM-5500",
        amount=60000,
        loss_type="total_loss",
    )
    _run_tool(
        "D: payout-agent $60k total loss (expected: BLOCK — English threshold)",
        "payout-agent",
        issue_claim_payout,
        claim_id="CLM-5500",
        amount=60000,
        loss_type="total_loss",
        metadata={"supervisor_approved": True},
    )
    _run_tool(
        "E: payout-agent $12k with supervisor (expected: ALLOW)",
        "payout-agent",
        issue_claim_payout,
        claim_id=CLAIM_ID,
        amount=12000,
        metadata={"supervisor_approved": True},
    )

    _header("Phase 4 — Scripted sequential crew (no LLM)")
    run_scripted_crew_workflow()

    _header("Phase 5 — Final response policy")
    _run_response(
        "G: claim fully approved language (expected: BLOCK)",
        "Your claim is fully approved and payment is guaranteed today.",
    )
    _run_response(
        "H: neutral status (expected: ALLOW)",
        "We received your claim and an adjuster will contact you within two business days.",
    )

    if args.crew:
        _header("Optional — Real CrewAI kickoff")
        try:
            from crew import kickoff_crew_if_configured
        except ImportError as exc:
            print(f"  Skipped: {exc}")
            return 0
        result = kickoff_crew_if_configured()
        if result is None:
            print("  Skipped: set OPENAI_API_KEY to run the live CrewAI crew.")
        else:
            print(result)
    else:
        print(
            "\nTip: run `python demo.py --crew` with OPENAI_API_KEY set to exercise "
            "the live CrewAI crew (tools still enforce policy via crew_tools.py)."
        )

    _header("Traces")
    trace = EXAMPLE_DIR / "openagentpolicy_traces" / "events.jsonl"
    if trace.exists():
        n = sum(1 for ln in trace.read_text().splitlines() if ln.strip())
        print(f"  {trace} ({n} events)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
