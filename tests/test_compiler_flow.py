from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from openagentpolicy import compile_english_policy
from openagentpolicy.cli.main import main
from openagentpolicy.inventory.schema import ArgumentSchema, Inventory, Tool
from openagentpolicy.runtime.decisions import DecisionType
from openagentpolicy.runtime.engine import PolicyRuntime
from openagentpolicy.runtime.events import PolicyEvent


def _inventory() -> Inventory:
    return Inventory(
        tools=[
            Tool(
                id="approve_loan",
                arguments={
                    "approved_amount": ArgumentSchema(type="number", aliases=["approved amount"]),
                    "approval_mode": ArgumentSchema(
                        type="string",
                        allowed_values=["auto", "manual"],
                        aliases=["approval mode"],
                    ),
                },
            )
        ]
    )


def test_compile_english_policy_success() -> None:
    result = compile_english_policy(
        english="If approved amount is greater than 5000, auto approval is not allowed.",
        inventory=_inventory(),
        policy_id="policy_auto_approval_threshold",
        action_hint={
            "type": "block",
            "message": "Auto approval is not allowed above 5000.",
        },
    )
    assert result.status.value == "compiled"
    assert result.compiled_policy is not None
    assert result.test_cases


def test_compile_english_policy_not_enforceable_when_missing_term() -> None:
    result = compile_english_policy(
        english="If KYC is not verified, do not approve loan.",
        inventory=_inventory(),
        policy_id="policy_kyc",
    )
    assert result.status.value in {"not_enforceable", "needs_review"}
    assert result.errors


def test_runtime_with_require_compiled_rejects_english_policy(tmp_path: Path) -> None:
    root = tmp_path / "app"
    policies_dir = root / "policies"
    policies_dir.mkdir(parents=True)
    (root / "inventory.yaml").write_text(
        yaml.dump({"tools": [{"id": "approve_loan", "arguments": {"approved_amount": {"type": "number"}}}]}),
        encoding="utf-8",
    )
    (policies_dir / "english.yaml").write_text(
        yaml.dump(
            {
                "id": "p1",
                "policy_type": "english",
                "english": "If approved amount is greater than 5000, auto approval is not allowed.",
            }
        ),
        encoding="utf-8",
    )
    (root / "openagentpolicy.yaml").write_text(
        yaml.dump(
            {
                "application": {"id": "app", "environment": "production"},
                "inventory": {"provider": "file", "path": "./inventory.yaml"},
                "compiler": {"enabled": False},
                "policies": {
                    "provider": "directory",
                    "path": "./policies",
                    "require_compiled": True,
                    "compile_on_startup": True,
                },
                "enforcement": {"fail_on_unenforceable": True},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(Exception):
        PolicyRuntime.from_config(root / "openagentpolicy.yaml")


def test_runtime_enforces_compiled_policy(tmp_path: Path) -> None:
    root = tmp_path / "app"
    policies_dir = root / "policies"
    policies_dir.mkdir(parents=True)
    (root / "inventory.yaml").write_text(
        yaml.dump(
            {
                "tools": [
                    {
                        "id": "approve_loan",
                        "arguments": {
                            "approved_amount": {"type": "number"},
                            "approval_mode": {"type": "string"},
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (policies_dir / "compiled.yaml").write_text(
        yaml.dump(
            {
                "id": "policy_auto_approval_threshold",
                "policy_type": "compiled",
                "trigger": {"event": "before_tool_call", "tool_id": "approve_loan"},
                "conditions": {
                    "all": [
                        {"field": "tool_args.approved_amount", "operator": ">", "value": 5000},
                        {"field": "tool_args.approval_mode", "operator": "==", "value": "auto"},
                    ]
                },
                "action": {"type": "block"},
                "source": {"compiled_at": "2026-01-01T00:00:00Z", "compiler_version": "1.0"},
                "validation": {"enforceability": "enforceable"},
            }
        ),
        encoding="utf-8",
    )
    (root / "openagentpolicy.yaml").write_text(
        yaml.dump(
            {
                "inventory": {"provider": "file", "path": "./inventory.yaml"},
                "compiler": {"enabled": False},
                "policies": {"provider": "directory", "path": "./policies", "require_compiled": True},
            }
        ),
        encoding="utf-8",
    )
    runtime = PolicyRuntime.from_config(root / "openagentpolicy.yaml")
    decision = runtime.process_event(
        PolicyEvent(
            event_type="before_tool_call",
            tool_id="approve_loan",
            tool_args={"approved_amount": 7000, "approval_mode": "auto"},
        )
    )
    assert decision.decision == DecisionType.BLOCK


def test_cli_compile_english_writes_output(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.yaml"
    output_path = tmp_path / "compiled.yaml"
    inventory_path.write_text(
        yaml.dump(
            {
                "tools": [
                    {
                        "id": "approve_loan",
                        "arguments": {
                            "approved_amount": {"type": "number", "aliases": ["approved amount"]},
                            "approval_mode": {"type": "string", "allowed_values": ["auto", "manual"]},
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    code = main(
        [
            "compile-english",
            "--inventory",
            str(inventory_path),
            "--policy-id",
            "policy_auto_approval_threshold",
            "--english",
            "If approved amount is greater than 5000, auto approval is not allowed.",
            "--output",
            str(output_path),
            "--action-hint",
            json.dumps({"type": "block"}),
        ]
    )
    assert code == 0
    assert output_path.exists()


def test_cli_compile_english_nonzero_for_not_enforceable(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.yaml"
    output_path = tmp_path / "compiled.yaml"
    inventory_path.write_text(
        yaml.dump({"tools": [{"id": "approve_loan", "arguments": {"approved_amount": {"type": "number"}}}]}),
        encoding="utf-8",
    )
    code = main(
        [
            "compile-english",
            "--inventory",
            str(inventory_path),
            "--policy-id",
            "policy_kyc",
            "--english",
            "If KYC is not verified, do not approve loan.",
            "--output",
            str(output_path),
        ]
    )
    assert code == 1
