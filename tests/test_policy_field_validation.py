from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from openagentpolicy.runtime.engine import PolicyRuntime


def _write_app(
    tmp_path: Path,
    *,
    policy: dict,
    fail_on_unresolved_fields: bool,
) -> Path:
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
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (policies_dir / "policy.yaml").write_text(yaml.dump(policy), encoding="utf-8")
    (root / "openagentpolicy.yaml").write_text(
        yaml.dump(
            {
                "inventory": {"provider": "file", "path": "./inventory.yaml"},
                "policies": {
                    "provider": "directory",
                    "path": "./policies",
                    "compile_on_startup": True,
                },
                "enforcement": {
                    "default_action": "allow",
                    "fail_on_unresolved_fields": fail_on_unresolved_fields,
                },
            }
        ),
        encoding="utf-8",
    )
    return root / "openagentpolicy.yaml"


def test_startup_fails_when_unresolved_fields_enabled(tmp_path: Path) -> None:
    config = _write_app(
        tmp_path,
        fail_on_unresolved_fields=True,
        policy={
            "id": "bad-field",
            "policy_type": "structured",
            "trigger": {"event": "before_tool_call", "tool_id": "approve_loan"},
            "conditions": {
                "field": "tool_args.non_existent",
                "operator": ">",
                "value": 1,
            },
            "action": {"type": "block"},
        },
    )
    with pytest.raises(ValueError, match="non_existent"):
        PolicyRuntime.from_config(config)


def test_startup_allows_when_unresolved_fields_disabled(tmp_path: Path) -> None:
    config = _write_app(
        tmp_path,
        fail_on_unresolved_fields=False,
        policy={
            "id": "bad-final-response-usage",
            "policy_type": "structured",
            "trigger": {"event": "before_final_response"},
            "conditions": {
                "field": "tool_args.approved_amount",
                "operator": ">",
                "value": 1,
            },
            "action": {"type": "block"},
        },
    )
    runtime = PolicyRuntime.from_config(config)
    assert runtime.policies


def test_after_tool_call_disallowed_action_fails_when_strict(tmp_path: Path) -> None:
    config = _write_app(
        tmp_path,
        fail_on_unresolved_fields=True,
        policy={
            "id": "after-modify-args",
            "policy_type": "structured",
            "trigger": {"event": "after_tool_call", "tool_id": "approve_loan"},
            "conditions": {
                "field": "tool_result.status",
                "operator": "==",
                "value": "approved",
            },
            "action": {"type": "modify_args", "set": {"approved_amount": 1}},
        },
    )
    with pytest.raises(ValueError, match="action.type"):
        PolicyRuntime.from_config(config)


def test_tool_metadata_field_is_allowed(tmp_path: Path) -> None:
    config = _write_app(
        tmp_path,
        fail_on_unresolved_fields=True,
        policy={
            "id": "risk-based-block",
            "policy_type": "structured",
            "trigger": {"event": "before_tool_call", "tool_id": "approve_loan"},
            "conditions": {
                "field": "tool.risk_level",
                "operator": "==",
                "value": "high",
            },
            "action": {"type": "block"},
        },
    )
    runtime = PolicyRuntime.from_config(config)
    assert runtime.policies
