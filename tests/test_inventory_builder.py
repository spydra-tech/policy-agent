from __future__ import annotations

import json
from pathlib import Path

import yaml

from openagentpolicy.cli.main import main
from openagentpolicy.traces.inventory_builder import (
    GeneratedInventory,
    TraceInventoryBuilder,
    load_trace_events,
)


def _write_sample_jsonl(path: Path) -> None:
    events = [
        {
            "event_type": "before_tool_call",
            "timestamp": "2026-05-26T10:00:00+00:00",
            "tool_id": "approve_loan",
            "trace_id": "trace-1",
            "tool_args": {
                "application_id": "app-1",
                "approved_amount": 5000,
                "approval_mode": "auto",
                "api_token": "***REDACTED***",
            },
            "decision": {"decision": "allow", "matched_policies": []},
        },
        {
            "event_type": "after_tool_call",
            "timestamp": "2026-05-26T10:00:01+00:00",
            "tool_id": "approve_loan",
            "trace_id": "trace-1",
            "tool_args": {
                "application_id": "app-1",
                "approved_amount": 5000,
                "approval_mode": "auto",
            },
            "tool_result": {"status": "approved", "risk_score": 0.2},
            "decision": {"decision": "allow", "matched_policies": []},
        },
        {
            "event_type": "before_tool_call",
            "timestamp": "2026-05-26T10:01:00+00:00",
            "tool_id": "check_balance",
            "trace_id": "trace-1",
            "tool_args": {"account_id": "acct-9"},
            "decision": {"decision": "allow", "matched_policies": []},
        },
        {
            "event_type": "after_tool_call",
            "timestamp": "2026-05-26T10:01:01+00:00",
            "tool_id": "check_balance",
            "trace_id": "trace-1",
            "tool_args": {"account_id": "acct-9"},
            "tool_result": {"balance": 12000},
            "decision": {"decision": "allow", "matched_policies": []},
        },
        {
            "event_type": "before_tool_call",
            "timestamp": "2026-05-26T10:02:00+00:00",
            "tool_id": "approve_loan",
            "trace_id": "trace-2",
            "tool_args": {
                "application_id": "app-2",
                "approved_amount": 250000,
                "approval_mode": "manual",
            },
            "decision": {"decision": "allow", "matched_policies": []},
        },
        {
            "event_type": "after_tool_call",
            "timestamp": "2026-05-26T10:02:01+00:00",
            "tool_id": "approve_loan",
            "trace_id": "trace-2",
            "tool_args": {
                "application_id": "app-2",
                "approved_amount": 250000,
                "approval_mode": "manual",
            },
            "tool_result": {"status": "approved", "risk_score": 0.8},
            "decision": {"decision": "allow", "matched_policies": []},
        },
    ]
    path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def test_build_inventory_from_sample_jsonl(tmp_path: Path) -> None:
    traces = tmp_path / "events.jsonl"
    _write_sample_jsonl(traces)

    builder = TraceInventoryBuilder()
    inventory = builder.build_from_jsonl(traces)

    assert inventory.generated_from.source == "traces"
    assert inventory.generated_from.trace_count == 2

    tool_ids = {tool.id for tool in inventory.tools}
    assert tool_ids == {"approve_loan", "check_balance"}

    approve = next(tool for tool in inventory.tools if tool.id == "approve_loan")
    amount = approve.observed_arguments["approved_amount"]
    assert amount.type == "number"
    assert amount.observed_min == 5000
    assert amount.observed_max == 250000
    assert amount.presence_rate == 1.0
    assert amount.policy_usable is True

    mode = approve.observed_arguments["approval_mode"]
    assert mode.type == "string"
    assert set(mode.observed_values or []) == {"auto", "manual"}
    assert mode.policy_usable is True

    token = approve.observed_arguments["api_token"]
    assert token.policy_usable is False

    assert approve.observed_result_fields["status"].type == "string"
    assert approve.observed_result_fields["risk_score"].type == "number"
    assert "check_balance" in approve.common_successors

    balance = next(tool for tool in inventory.tools if tool.id == "check_balance")
    assert "approve_loan" in balance.common_predecessors


def test_write_generated_inventory_yaml(tmp_path: Path) -> None:
    traces = tmp_path / "events.jsonl"
    output = tmp_path / "generated_inventory.yaml"
    _write_sample_jsonl(traces)

    builder = TraceInventoryBuilder()
    inventory = builder.build_from_jsonl(traces)
    builder.write_yaml(inventory, output)

    data = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert data["generated_from"]["source"] == "traces"
    assert data["tools"][0]["id"] in {"approve_loan", "check_balance"}
    assert "observed_arguments" in data["tools"][0]


def test_cli_generate_inventory_command(tmp_path: Path) -> None:
    traces = tmp_path / "events.jsonl"
    output = tmp_path / "generated_inventory.yaml"
    _write_sample_jsonl(traces)

    exit_code = main(
        [
            "generate-inventory",
            "--traces",
            str(traces),
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    assert output.exists()

    inventory = GeneratedInventory.model_validate(
        yaml.safe_load(output.read_text(encoding="utf-8"))
    )
    assert len(inventory.tools) == 2


def test_load_trace_events(tmp_path: Path) -> None:
    traces = tmp_path / "events.jsonl"
    _write_sample_jsonl(traces)
    events = load_trace_events(traces)
    assert len(events) == 6
