from __future__ import annotations

from pathlib import Path

import yaml

from openagentpolicy import agent_session, configure, policy_tool
from openagentpolicy.annotations import PolicyViolation, reset_runtime
from openagentpolicy.runtime.events import PolicyEvent


@policy_tool(id="approve_loan")
def approve_loan(approved_amount: float) -> dict[str, float]:
    return {"approved_amount": approved_amount}


def _write_agentic_config(tmp_path: Path) -> Path:
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
        )
    )
    (policies_dir / "agent_only.yaml").write_text(
        yaml.dump(
            {
                "id": "agent_only",
                "enabled": True,
                "policy_type": "structured",
                "trigger": {
                    "event": "before_tool_call",
                    "tool_id": "approve_loan",
                },
                "conditions": {
                    "field": "agent_id",
                    "operator": "!=",
                    "value": "loan-agent",
                },
                "action": {"type": "block", "message": "wrong agent"},
            }
        )
    )
    config_path = root / "openagentpolicy.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "inventory": {"provider": "file", "path": "./inventory.yaml"},
                "policies": {
                    "provider": "directory",
                    "path": "./policies",
                    "support_english": True,
                },
                "enforcement": {"default_action": "allow", "audit_enabled": False},
            }
        )
    )
    return config_path


def test_agent_session_propagates_agent_id_to_events(tmp_path: Path) -> None:
    reset_runtime()
    config_path = _write_agentic_config(tmp_path)
    runtime = configure(config_path)

    captured: list[PolicyEvent] = []
    original = runtime.process_event

    def capture(event: PolicyEvent, **kwargs: object) -> object:
        captured.append(event)
        return original(event, **kwargs)  # type: ignore[arg-type]

    runtime.process_event = capture  # type: ignore[method-assign]

    with agent_session("loan-agent", metadata={"human_reviewed": True}):
        approve_loan(approved_amount=1000)

    before_events = [
        e for e in captured if e.event_type == "before_tool_call"
    ]
    assert before_events
    assert before_events[0].agent_id == "loan-agent"
    assert before_events[0].metadata.get("human_reviewed") is True


def test_wrong_agent_blocked_by_policy(tmp_path: Path) -> None:
    reset_runtime()
    config_path = _write_agentic_config(tmp_path)
    configure(config_path)

    with agent_session("loan-agent"):
        assert approve_loan(approved_amount=100)["approved_amount"] == 100

    try:
        with agent_session("compliance-agent"):
            approve_loan(approved_amount=100)
        raise AssertionError("expected PolicyViolation")
    except PolicyViolation as exc:
        assert exc.decision is not None
        assert exc.decision.decision.value == "block"
