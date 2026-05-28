from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from openagentpolicy.annotations import (
    PolicyViolation,
    configure,
    policy_tool,
    reset_runtime,
)
from openagentpolicy.traces.recorder import (
    LocalTraceRecorder,
    redact_sensitive_dict,
)


@pytest.fixture(autouse=True)
def _reset_global_runtime() -> None:
    reset_runtime()
    yield
    reset_runtime()


def _write_trace_fixture(tmp_path: Path, *, policies: list[dict] | None = None) -> Path:
    root = tmp_path / "app"
    policies_dir = root / "policies"
    policies_dir.mkdir(parents=True)
    trace_dir = root / "traces"

    if policies:
        for index, policy in enumerate(policies):
            (policies_dir / f"policy_{index}.yaml").write_text(
                yaml.dump(policy), encoding="utf-8"
            )

    (root / "inventory.yaml").write_text(
        yaml.dump(
            {
                "tools": [
                    {
                        "id": "approve_loan",
                        "arguments": {
                            "application_id": {"type": "string"},
                            "approved_amount": {"type": "number"},
                            "customer_identifier": {
                                "type": "string",
                                "sensitive": True,
                            },
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "openagentpolicy.yaml").write_text(
        yaml.dump(
            {
                "inventory": {"provider": "file", "path": "./inventory.yaml"},
                "policies": {"provider": "directory", "path": "./policies"},
                "traces": {
                    "enabled": True,
                    "store": {"provider": "local", "path": "./traces"},
                },
            }
        ),
        encoding="utf-8",
    )
    return root / "openagentpolicy.yaml"


def test_annotated_tool_writes_before_and_after_events(tmp_path: Path) -> None:
    config = _write_trace_fixture(tmp_path)
    configure(config)

    @policy_tool
    def approve_loan(application_id: str, approved_amount: float) -> dict[str, str]:
        return {"status": "approved", "application_id": application_id}

    result = approve_loan("app-1", 100.0)
    assert result["status"] == "approved"

    events_path = tmp_path / "app" / "traces" / "events.jsonl"
    assert events_path.exists()
    lines = [line for line in events_path.read_text().splitlines() if line.strip()]
    assert len(lines) == 2

    events = [json.loads(line) for line in lines]
    assert events[0]["event_type"] == "before_tool_call"
    assert events[1]["event_type"] == "after_tool_call"


def test_sensitive_keys_are_redacted() -> None:
    data = {
        "user": "alice",
        "api_token": "secret-token",
        "nested": {"client_secret": "abc", "amount": 10},
        "password_hash": "hashed",
        "pan_number": "1111-2222-3333-4444",
        "aadhaar_no": "123412341234",
        "ssn_last4": "9999",
    }
    redacted = redact_sensitive_dict(data)
    assert redacted["user"] == "alice"
    assert redacted["api_token"] == "***REDACTED***"
    assert redacted["password_hash"] == "***REDACTED***"
    assert redacted["pan_number"] == "***REDACTED***"
    assert redacted["aadhaar_no"] == "***REDACTED***"
    assert redacted["ssn_last4"] == "***REDACTED***"
    assert redacted["nested"]["client_secret"] == "***REDACTED***"
    assert redacted["nested"]["amount"] == 10


def test_event_contains_tool_id_args_result_and_decision(tmp_path: Path) -> None:
    config = _write_trace_fixture(
        tmp_path,
        policies=[
            {
                "id": "block-large",
                "trigger": {
                    "event": "before_tool_call",
                    "tool_id": "approve_loan",
                },
                "conditions": {
                    "field": "tool_args.approved_amount",
                    "operator": ">",
                    "value": 10000,
                },
                "action": {"type": "block", "message": "Too large"},
            }
        ],
    )
    configure(config)

    @policy_tool
    def approve_loan(
        application_id: str,
        approved_amount: float,
        api_token: str = "tok",
    ) -> dict[str, object]:
        return {"status": "approved", "amount": approved_amount}

    approve_loan("app-1", 500.0, api_token="visible")

    events_path = tmp_path / "app" / "traces" / "events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text().splitlines()
        if line.strip()
    ]
    before = events[0]
    after = events[1]

    assert before["tool_id"] == "approve_loan"
    assert before["tool_args"]["application_id"] == "app-1"
    assert before["tool_args"]["approved_amount"] == 500.0
    assert before["tool_args"]["api_token"] == "***REDACTED***"
    assert before["tool_result"] is None
    assert before["decision"]["decision"] == "allow"

    assert after["tool_id"] == "approve_loan"
    assert after["tool_result"]["status"] == "approved"
    assert after["tool_result"]["amount"] == 500.0
    assert after["decision"]["decision"] == "allow"

    with pytest.raises(PolicyViolation):
        approve_loan("app-2", 50000.0)

    blocked_events = LocalTraceRecorder(events_path).read_events()
    blocked_before = blocked_events[2]
    assert blocked_before["event_type"] == "before_tool_call"
    assert blocked_before["decision"]["decision"] == "block"
    assert blocked_before["decision"]["message"] == "Too large"


def test_inventory_sensitive_argument_is_redacted(tmp_path: Path) -> None:
    config = _write_trace_fixture(tmp_path)
    configure(config)

    @policy_tool
    def approve_loan(
        application_id: str,
        approved_amount: float,
        customer_identifier: str,
    ) -> dict[str, object]:
        return {"status": "approved", "customer_identifier": customer_identifier}

    approve_loan("app-3", 100.0, customer_identifier="CUST-12345")

    events_path = tmp_path / "app" / "traces" / "events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text().splitlines()
        if line.strip()
    ]
    assert events[0]["tool_args"]["customer_identifier"] == "***REDACTED***"
