"""Agentic loan desk demo: English compile, tool policies, agent policies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from openagentpolicy import configure
from openagentpolicy.annotations import PolicyViolation
from openagentpolicy.cli.validate import compile_policy_file

from agent_session import finalize_response, run_as_agent
from tools import approve_loan, send_to_human_review

EXAMPLE_DIR = Path(__file__).parent
INVENTORY = EXAMPLE_DIR / "inventory.yaml"
POLICIES = EXAMPLE_DIR / "policies"


def _print_header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print("=" * 60)


def _show_compile(path: Path) -> None:
    results = compile_policy_file(path, INVENTORY)
    for result in results:
        print(f"\nPolicy file: {path.name}")
        print(f"  policy_id: {result.get('policy_id')}")
        print(f"  compile_status: {result.get('compile_status')}")
        print(f"  confidence: {result.get('confidence')}")
        if result.get("resolved_terms"):
            print(f"  resolved_terms: {result['resolved_terms']}")
        compiled = result.get("compiled_policy")
        if compiled:
            trigger = compiled.get("trigger") or {}
            print(f"  trigger: event={trigger.get('event')!r}, tool_id={trigger.get('tool_id')!r}")
            print(f"  conditions: {json.dumps(compiled.get('conditions'), indent=4)}")


def _run_tool_scenario(
    label: str,
    agent_id: str,
    fn: Callable[..., Any],
    /,
    *args: Any,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    print(f"\n--- {label} ---")
    print(f"agent={agent_id!r}")
    arg_preview = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    print(f"call: {fn.__name__}({arg_preview})")
    if metadata:
        print(f"metadata: {metadata}")
    try:
        result = run_as_agent(agent_id, fn, metadata=metadata, **kwargs)
        print("Result: ALLOWED")
        print(f"  {result}")
    except PolicyViolation as exc:
        print("Result: BLOCKED")
        print(f"  {exc}")
        if exc.decision:
            print(f"  decision={exc.decision.decision.value}")
            if exc.decision.message:
                print(f"  message={exc.decision.message!r}")
            if exc.decision.matched_policies:
                print(f"  matched_policies={exc.decision.matched_policies}")


def _run_response_scenario(label: str, agent_id: str, text: str) -> None:
    print(f"\n--- {label} ---")
    print(f"agent={agent_id!r}")
    print(f"response: {text!r}")
    try:
        finalize_response(text, agent_id=agent_id)
        print("Result: ALLOWED")
    except PolicyViolation as exc:
        print("Result: BLOCKED")
        print(f"  {exc}")
        if exc.decision and exc.decision.message:
            print(f"  message={exc.decision.message!r}")


def main() -> None:
    configure(EXAMPLE_DIR / "openagentpolicy.yaml")

    _print_header("Phase 1 — English policy compilation")
    print("English policies compile to structured rules using inventory.yaml.")
    _show_compile(POLICIES / "01_tool_high_value_english.yaml")
    _show_compile(POLICIES / "02_agent_only_loan_agent_english.yaml")

    _print_header("Phase 2 — Tool-level enforcement (English)")
    _run_tool_scenario(
        "Scenario A: loan-agent, $4k auto (expected: ALLOW)",
        "loan-agent",
        approve_loan,
        application_id="app-2001",
        approved_amount=4000,
        approval_mode="auto",
    )
    _run_tool_scenario(
        "Scenario B: loan-agent, $7k auto (expected: BLOCK — tool policy)",
        "loan-agent",
        approve_loan,
        application_id="app-2002",
        approved_amount=7000,
        approval_mode="auto",
    )

    _print_header("Phase 3 — Agent-level enforcement (English allowlist)")
    _run_tool_scenario(
        "Scenario C: compliance-agent, $4k auto (expected: BLOCK — agent policy)",
        "compliance-agent",
        approve_loan,
        application_id="app-2003",
        approved_amount=4000,
        approval_mode="auto",
    )

    _print_header("Phase 4 — Workflow metadata (structured agent policy)")
    _run_tool_scenario(
        "Scenario D1: loan-agent, $7k manual without review (expected: BLOCK)",
        "loan-agent",
        approve_loan,
        application_id="app-2004",
        approved_amount=7000,
        approval_mode="manual",
        metadata={"human_reviewed": False},
    )
    print("\n  (escalating to human review...)")
    run_as_agent(
        "loan-agent",
        send_to_human_review,
        application_id="app-2004",
        reason="Amount exceeds auto-approval threshold",
    )
    _run_tool_scenario(
        "Scenario D2: loan-agent, $7k manual after review (expected: ALLOW)",
        "loan-agent",
        approve_loan,
        application_id="app-2004",
        approved_amount=7000,
        approval_mode="manual",
        metadata={"human_reviewed": True},
    )

    _print_header("Phase 5 — Agent final response (structured)")
    _run_response_scenario(
        "Scenario E: unsafe guarantee language (expected: BLOCK)",
        "loan-agent",
        "We offer guaranteed approval on all applications.",
    )
    _run_response_scenario(
        "Scenario E2: safe response (expected: ALLOW)",
        "loan-agent",
        "Your application is under review and we will respond within two business days.",
    )

    _print_header("Traces")
    traces_file = EXAMPLE_DIR / "openagentpolicy_traces" / "events.jsonl"
    if traces_file.exists():
        lines = [line for line in traces_file.read_text().splitlines() if line.strip()]
        print(f"Trace events: {traces_file}")
        print(f"Event count: {len(lines)}")
    else:
        print(f"No trace file at {traces_file}")


if __name__ == "__main__":
    main()
