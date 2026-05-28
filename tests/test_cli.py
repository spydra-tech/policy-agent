from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from openagentpolicy.cli.main import main
from openagentpolicy.cli.validate import ValidationError


EXAMPLE = Path(__file__).parent.parent / "examples" / "loan_approval_basic"


def test_validate_config() -> None:
    assert main(["validate-config", str(EXAMPLE / "openagentpolicy.yaml")]) == 0


def test_validate_inventory() -> None:
    assert main(["validate-inventory", str(EXAMPLE / "inventory.yaml")]) == 0


def test_validate_policy() -> None:
    assert (
        main(
            [
                "validate-policy",
                str(EXAMPLE / "policies" / "auto_approval_structured.yaml"),
                "--inventory",
                str(EXAMPLE / "inventory.yaml"),
            ]
        )
        == 0
    )


def test_validate_policy_fails_unknown_tool(tmp_path: Path) -> None:
    policy = tmp_path / "bad.yaml"
    inventory = tmp_path / "inventory.yaml"
    policy.write_text(
        yaml.dump(
            {
                "id": "bad",
                "trigger": {"event": "before_tool_call", "tool_id": "missing"},
                "action": {"type": "block"},
            }
        ),
        encoding="utf-8",
    )
    inventory.write_text(
        yaml.dump({"tools": [{"id": "approve_loan"}]}),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "validate-policy",
                str(policy),
                "--inventory",
                str(inventory),
            ]
        )
        == 1
    )


def test_compile_policy_structured() -> None:
    exit_code = main(
        [
            "compile-policy",
            str(EXAMPLE / "policies" / "auto_approval_structured.yaml"),
            "--inventory",
            str(EXAMPLE / "inventory.yaml"),
        ]
    )
    assert exit_code == 0


def test_test_policy_blocks_high_value_loan() -> None:
    exit_code = main(
        [
            "test-policy",
            str(EXAMPLE / "policies" / "auto_approval_structured.yaml"),
            "--event",
            str(EXAMPLE / "events" / "high_value_loan.json"),
            "--inventory",
            str(EXAMPLE / "inventory.yaml"),
        ]
    )
    assert exit_code == 1


def test_test_policy_allows_small_loan(tmp_path: Path) -> None:
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "event_type": "before_tool_call",
                "tool_id": "approve_loan",
                "tool_args": {"amount": 1000, "risk_score": 0.2},
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "test-policy",
                str(EXAMPLE / "policies" / "auto_approval_structured.yaml"),
                "--event",
                str(event),
                "--inventory",
                str(EXAMPLE / "inventory.yaml"),
            ]
        )
        == 0
    )


def test_generate_inventory_cli(tmp_path: Path) -> None:
    from tests.test_inventory_builder import _write_sample_jsonl

    traces = tmp_path / "events.jsonl"
    output = tmp_path / "generated_inventory.yaml"
    _write_sample_jsonl(traces)
    assert (
        main(
            [
                "generate-inventory",
                "--traces",
                str(traces),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.exists()


def test_explain_command_outputs_summary(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "explain",
            "--config",
            str(EXAMPLE / "openagentpolicy.yaml"),
            "--format",
            "json",
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "loaded_policies" in payload
    assert "compiled_policies" in payload
    assert "unenforceable_policies" in payload
    assert "inventory_mismatches" in payload
