#!/usr/bin/env python3
"""LangGraph stock research demo with English policy enforcement.

Run from this directory after installing dependencies:

    pip install -e "../.."   # or repo root
    pip install -r requirements.txt
    cd examples/agentic_stock_research
    python demo.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openagentpolicy import configure
from openagentpolicy.annotations import PolicyViolation
from openagentpolicy.cli.validate import compile_policy_file

from agent_session import finalize_graph_output
from graph import StockResearchState, build_stock_research_graph

EXAMPLE_DIR = Path(__file__).parent
INVENTORY = EXAMPLE_DIR / "inventory.yaml"
POLICIES = EXAMPLE_DIR / "policies"
CONFIG = EXAMPLE_DIR / "openagentpolicy.yaml"


def _header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print("=" * 60)


def _show_english_compile(path: Path) -> None:
    for result in compile_policy_file(path, INVENTORY):
        print(f"\n  {path.name}: {result.get('compile_status')} "
              f"(policy_id={result.get('policy_id')})")


def _run_graph_scenario(
    label: str,
    *,
    initial: StockResearchState,
    check_final: bool = True,
) -> None:
    print(f"\n--- {label} ---")
    print(f"  agent_id={initial.get('agent_id')!r}")
    if initial.get("metadata"):
        print(f"  metadata={initial['metadata']}")
    graph = build_stock_research_graph()
    out: dict[str, Any] = dict(graph.invoke(initial))
    if out.get("policy_blocked"):
        print(f"  Result: POLICY BLOCKED during graph")
        print(f"  {out.get('policy_error')}")
        return
    final = out.get("final_message", "")
    if check_final:
        try:
            safe_state = finalize_graph_output(out)
            final = safe_state.get("final_message", final)
            print("  Result: ALLOWED (final response passed policy)")
            print(f"  Message: {final!r}")
        except PolicyViolation as exc:
            print("  Result: BLOCKED (final response policy)")
            print(f"  {exc}")
    else:
        print(f"  Result: graph completed")
        print(f"  Message: {final!r}")
    if out.get("trade_result"):
        print(f"  trade_result={out['trade_result']}")
    if out.get("note_result"):
        print(f"  note_result={out['note_result']}")


def main() -> None:
    configure(CONFIG)

    _header("Phase 1 — English policy compilation (rule-based CLI)")
    for name in (
        "01_block_large_order_english.yaml",
        "02_only_trading_desk_may_trade_english.yaml",
        "05_retail_no_save_note_english.yaml",
    ):
        _show_english_compile(POLICIES / name)

    _header("Phase 2 — LangGraph research flow (read-only tools)")
    _run_graph_scenario(
        "A: research-agent gathers AAPL quote + news (expected: ALLOW)",
        initial={
            "agent_id": "research-agent",
            "symbol": "AAPL",
            "quantity": 10.0,
            "attempt_trade": False,
            "attempt_save_note": False,
            "metadata": {},
        },
    )

    _header("Phase 3 — Trade policies (English + metadata)")
    _run_graph_scenario(
        "B: research-agent tries to buy 50 shares (expected: BLOCK — agent allowlist)",
        initial={
            "agent_id": "research-agent",
            "symbol": "NVDA",
            "quantity": 50.0,
            "attempt_trade": True,
            "metadata": {"compliance_cleared": True},
        },
        check_final=False,
    )
    _run_graph_scenario(
        "C: trading-desk, 50 shares, no compliance flag (expected: BLOCK — compliance)",
        initial={
            "agent_id": "trading-desk-agent",
            "symbol": "NVDA",
            "quantity": 50.0,
            "attempt_trade": True,
            "metadata": {"compliance_cleared": False},
        },
        check_final=False,
    )
    _run_graph_scenario(
        "D: trading-desk, 150 shares, compliance cleared (expected: BLOCK — size English)",
        initial={
            "agent_id": "trading-desk-agent",
            "symbol": "NVDA",
            "quantity": 150.0,
            "attempt_trade": True,
            "metadata": {"compliance_cleared": True},
        },
        check_final=False,
    )
    _run_graph_scenario(
        "E: trading-desk, 40 shares, compliance cleared (expected: ALLOW trade)",
        initial={
            "agent_id": "trading-desk-agent",
            "symbol": "AAPL",
            "quantity": 40.0,
            "attempt_trade": True,
            "metadata": {"compliance_cleared": True},
        },
        check_final=False,
    )

    _header("Phase 4 — Research-note agent policy (English)")
    _run_graph_scenario(
        "F: retail-copilot tries to save a note (expected: BLOCK)",
        initial={
            "agent_id": "retail-copilot-agent",
            "symbol": "TSLA",
            "quantity": 0.0,
            "attempt_save_note": True,
            "note": "Retail user draft note",
            "metadata": {},
        },
        check_final=False,
    )

    _header("Phase 5 — Final response policy (structured)")
    print("\n--- G: unsafe guaranteed-returns language (expected: BLOCK) ---")
    try:
        finalize_graph_output(
            {
                "agent_id": "research-agent",
                "metadata": {},
                "final_message": "This strategy offers guaranteed returns every quarter.",
            }
        )
        print("  Result: ALLOWED (unexpected)")
    except PolicyViolation as exc:
        print(f"  Result: BLOCKED — {exc}")

    print("\n--- H: compliant research summary (expected: ALLOW) ---")
    try:
        state = finalize_graph_output(
            {
                "agent_id": "research-agent",
                "metadata": {},
                "final_message": (
                    "AAPL trades near $198 in our demo feed; consider your risk tolerance."
                ),
            }
        )
        print(f"  Result: ALLOWED — {state['final_message']!r}")
    except PolicyViolation as exc:
        print(f"  Result: BLOCKED — {exc}")

    _header("Traces")
    trace_file = EXAMPLE_DIR / "openagentpolicy_traces" / "events.jsonl"
    if trace_file.exists():
        lines = [ln for ln in trace_file.read_text().splitlines() if ln.strip()]
        print(f"  {trace_file} ({len(lines)} events)")
    else:
        print(f"  No trace file yet at {trace_file}")


if __name__ == "__main__":
    main()
