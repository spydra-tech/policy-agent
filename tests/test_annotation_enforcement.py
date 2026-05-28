from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from openagentpolicy.annotations import (
    PolicyViolation,
    configure,
    get_runtime,
    policy_tool,
    reset_runtime,
)


@pytest.fixture(autouse=True)
def _reset_global_runtime() -> None:
    reset_runtime()
    yield
    reset_runtime()


def _write_enforcement_fixture(
    tmp_path: Path,
    *,
    policies: list[dict] | None = None,
    tools: list[dict] | None = None,
) -> Path:
    root = tmp_path / "app"
    policies_dir = root / "policies"
    policies_dir.mkdir(parents=True)

    if policies:
        for index, policy in enumerate(policies):
            (policies_dir / f"policy_{index}.yaml").write_text(
                yaml.dump(policy), encoding="utf-8"
            )

    inventory = {"tools": tools or []}
    (root / "inventory.yaml").write_text(
        yaml.dump(inventory), encoding="utf-8"
    )
    (root / "openagentpolicy.yaml").write_text(
        yaml.dump(
            {
                "inventory": {"provider": "file", "path": "./inventory.yaml"},
                "policies": {"provider": "directory", "path": "./policies"},
            }
        ),
        encoding="utf-8",
    )
    return root / "openagentpolicy.yaml"


def test_function_runs_when_no_policy_matches(tmp_path: Path) -> None:
    config = _write_enforcement_fixture(
        tmp_path,
        tools=[{"id": "approve_loan"}],
    )
    configure(config)

    @policy_tool
    def approve_loan(application_id: str, approved_amount: float) -> dict[str, str]:
        return {"status": "approved", "application_id": application_id}

    result = approve_loan("app-1", 5000.0)
    assert result == {"status": "approved", "application_id": "app-1"}


def test_function_blocks_when_policy_matches(tmp_path: Path) -> None:
    config = _write_enforcement_fixture(
        tmp_path,
        tools=[{"id": "approve_loan"}],
        policies=[
            {
                "id": "block-large",
                "trigger": {
                    "event": "before_tool_call",
                    "tool_id": "approve_loan",
                },
                "conditions": {
                    "field": "approved_amount",
                    "operator": ">",
                    "value": 10000,
                },
                "action": {"type": "block", "message": "Amount too large"},
            }
        ],
    )
    configure(config)

    @policy_tool
    def approve_loan(application_id: str, approved_amount: float) -> dict[str, str]:
        return {"status": "approved"}

    with pytest.raises(PolicyViolation, match="Amount too large"):
        approve_loan("app-1", 25000.0)


def test_function_args_captured_correctly(tmp_path: Path) -> None:
    config = _write_enforcement_fixture(
        tmp_path,
        tools=[{"id": "approve_loan"}],
    )
    configure(config)

    @policy_tool
    def approve_loan(
        application_id: str,
        approved_amount: float,
        approval_mode: str = "standard",
    ) -> dict[str, str]:
        return {"status": "approved"}

    approve_loan("app-42", 1200.0, approval_mode="express")

    events = get_runtime().audit.events()
    before = next(e for e in events if e.event_type == "before_tool_call")
    assert before.tool_id == "approve_loan"
    assert before.tool_args == {
        "application_id": "app-42",
        "approved_amount": 1200.0,
        "approval_mode": "express",
    }


def test_tool_id_defaults_to_function_name(tmp_path: Path) -> None:
    from openagentpolicy.annotations import get_tool_definition

    config = _write_enforcement_fixture(tmp_path)
    configure(config)

    @policy_tool
    def approve_loan(application_id: str, approved_amount: float) -> dict[str, str]:
        return {"status": "approved"}

    definition = get_tool_definition(approve_loan)
    assert definition is not None
    assert definition.id == "approve_loan"

    approve_loan("app-1", 1.0)
    events = get_runtime().audit.events()
    before = next(e for e in events if e.event_type == "before_tool_call")
    assert before.tool_id == "approve_loan"


def test_audit_log_redacts_sensitive_args_from_inventory(tmp_path: Path) -> None:
    config = _write_enforcement_fixture(
        tmp_path,
        tools=[
            {
                "id": "approve_loan",
                "arguments": {
                    "application_id": {"type": "string"},
                    "customer_identifier": {"type": "string", "sensitive": True},
                },
            }
        ],
    )
    configure(config)

    @policy_tool
    def approve_loan(
        application_id: str,
        customer_identifier: str,
    ) -> dict[str, str]:
        return {"status": "approved"}

    approve_loan("app-1", "cust-999")
    events = get_runtime().audit.events()
    before = next(e for e in events if e.event_type == "before_tool_call")
    assert before.tool_args["application_id"] == "app-1"
    assert before.tool_args["customer_identifier"] == "***REDACTED***"


def test_after_tool_call_block_is_ignored(tmp_path: Path) -> None:
    config = _write_enforcement_fixture(
        tmp_path,
        tools=[{"id": "approve_loan"}],
        policies=[
            {
                "id": "after-block",
                "trigger": {
                    "event": "after_tool_call",
                    "tool_id": "approve_loan",
                },
                "conditions": {
                    "field": "tool_result.status",
                    "operator": "==",
                    "value": "approved",
                },
                "action": {"type": "block", "message": "too late to block"},
            }
        ],
    )
    configure(config)

    @policy_tool
    def approve_loan(application_id: str, approved_amount: float) -> dict[str, str]:
        return {"status": "approved"}

    result = approve_loan("app-7", 42.0)
    assert result["status"] == "approved"
