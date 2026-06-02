#!/usr/bin/env python3
"""Procurement desk demo: English policies on PO creation and vendor payments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from openagentpolicy import configure
from openagentpolicy.annotations import PolicyViolation
from openagentpolicy.cli.validate import compile_policy_file

from agent_session import finalize_response, run_as_agent
from tools import approve_vendor_payment, create_purchase_order, lookup_vendor

EXAMPLE_DIR = Path(__file__).parent
INVENTORY = EXAMPLE_DIR / "inventory.yaml"
POLICIES = EXAMPLE_DIR / "policies"


def _header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print("=" * 60)


def _show_compile(path: Path) -> None:
    for result in compile_policy_file(path, INVENTORY):
        print(f"\n  {path.name}: {result.get('compile_status')} "
              f"(policy_id={result.get('policy_id')})")


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
    print(f"  call={fn.__name__}({', '.join(f'{k}={v!r}' for k, v in kwargs.items())})")
    try:
        result = run_as_agent(agent_id, fn, metadata=metadata, **kwargs)
        print("  Result: ALLOWED")
        print(f"  {result}")
    except PolicyViolation as exc:
        print("  Result: BLOCKED")
        print(f"  {exc}")
        if exc.decision and exc.decision.matched_policies:
            print(f"  matched_policies={exc.decision.matched_policies}")


def _run_response(label: str, agent_id: str, text: str) -> None:
    print(f"\n--- {label} ---")
    print(f"  response={text!r}")
    try:
        finalize_response(text, agent_id=agent_id)
        print("  Result: ALLOWED")
    except PolicyViolation as exc:
        print("  Result: BLOCKED")
        print(f"  {exc}")


def main() -> None:
    configure(EXAMPLE_DIR / "openagentpolicy.yaml")

    _header("Phase 1 — English policy compilation")
    for name in (
        "01_block_large_equipment_po_english.yaml",
        "02_only_procurement_may_approve_payment_english.yaml",
        "05_only_procurement_may_create_po_english.yaml",
    ):
        _show_compile(POLICIES / name)

    _header("Phase 2 — Read-only + PO creation")
    run_as_agent("requester-agent", lookup_vendor, vendor_id="V-100")
    print("  requester lookup_vendor: OK")
    _run_tool(
        "A: procurement-agent, $8k software PO (expected: ALLOW)",
        "procurement-agent",
        create_purchase_order,
        vendor_id="V-100",
        amount=8000,
        category="software",
    )
    _run_tool(
        "A2: requester, $8k software PO (expected: BLOCK — only procurement may create PO)",
        "requester-agent",
        create_purchase_order,
        vendor_id="V-100",
        amount=8000,
        category="software",
    )

    _header("Phase 3 — PO policies (English)")
    _run_tool(
        "B: requester, $30k equipment PO (expected: BLOCK — size/category English)",
        "requester-agent",
        create_purchase_order,
        vendor_id="V-200",
        amount=30000,
        category="equipment",
    )
    _run_tool(
        "C: finance-agent tries to create PO (expected: BLOCK — only procurement)",
        "finance-agent",
        create_purchase_order,
        vendor_id="V-100",
        amount=5000,
        category="services",
    )

    _header("Phase 4 — Payment policies (English + metadata)")
    po = run_as_agent(
        "procurement-agent",
        create_purchase_order,
        vendor_id="V-100",
        amount=12000,
        category="software",
    )
    po_id = po["po_id"]
    print(f"\n  (setup PO {po_id} as procurement-agent)")

    _run_tool(
        "D: finance-agent approves payment (expected: BLOCK — agent allowlist)",
        "finance-agent",
        approve_vendor_payment,
        po_id=po_id,
        amount=12000,
    )
    _run_tool(
        "E: procurement, $15k payment, no budget sign-off (expected: BLOCK — metadata)",
        "procurement-agent",
        approve_vendor_payment,
        po_id=po_id,
        amount=15000,
        metadata={"budget_holder_approved": False},
    )
    _run_tool(
        "F: procurement, $9k payment, budget approved (expected: ALLOW)",
        "procurement-agent",
        approve_vendor_payment,
        po_id=po_id,
        amount=9000,
        metadata={"budget_holder_approved": True},
    )

    _header("Phase 5 — Final response policy")
    _run_response(
        "G: guaranteed savings language (expected: BLOCK)",
        "procurement-agent",
        "This vendor contract delivers guaranteed savings of 20% every year.",
    )
    _run_response(
        "H: neutral summary (expected: ALLOW)",
        "procurement-agent",
        "PO is within policy; finance review is recommended before fiscal close.",
    )

    _header("Traces")
    trace = EXAMPLE_DIR / "openagentpolicy_traces" / "events.jsonl"
    if trace.exists():
        n = sum(1 for line in trace.read_text().splitlines() if line.strip())
        print(f"  {trace} ({n} events)")
    else:
        print(f"  No trace file at {trace}")


if __name__ == "__main__":
    main()
