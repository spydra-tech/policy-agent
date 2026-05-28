from pathlib import Path

import yaml

from openagentpolicy.config import EngineConfig, load_config
from openagentpolicy.runtime.decisions import DecisionType
from openagentpolicy.runtime.engine import PolicyRuntime


def test_load_config_full_example(tmp_path: Path) -> None:
    config_data = {
        "application": {
            "id": "loan_approval_app",
            "name": "Loan Approval App",
            "environment": "production",
        },
        "runtime": {"default_agent_id": "loan_decision_agent"},
        "inventory": {"provider": "file", "path": "./inventory.yaml"},
        "policies": {
            "provider": "directory",
            "path": "./policies",
            "support_english": True,
            "compile_on_startup": True,
            "english_compiler": "hybrid",
            "ai": {
                "model": "gpt-4.1-mini",
                "require_review_below_confidence": 0.9,
            },
        },
        "enforcement": {
            "default_action": "allow",
            "on_policy_error": "allow_with_warning",
            "audit_enabled": True,
            "fail_on_unresolved_fields": True,
            "fail_on_unenforceable": True,
        },
    }
    config_path = tmp_path / "openagentpolicy.yaml"
    config_path.write_text(yaml.dump(config_data), encoding="utf-8")

    config = load_config(config_path)
    assert config.application is not None
    assert config.application.id == "loan_approval_app"
    assert config.runtime.default_agent_id == "loan_decision_agent"
    assert config.inventory.provider == "file"
    assert config.inventory.conflict_strategy == "merge_with_warning"
    assert config.policies.provider == "directory"
    assert config.policies.english_compiler == "hybrid"
    assert config.policies.ai["model"] == "gpt-4.1-mini"
    assert config.enforcement.default_action == DecisionType.ALLOW
    assert config.enforcement.fail_on_unresolved_fields is True
    assert config.enforcement.fail_on_unenforceable is True


def test_runtime_loads_inventory_and_policies_on_configure(tmp_path: Path) -> None:
    root = tmp_path / "app"
    policies_dir = root / "policies"
    policies_dir.mkdir(parents=True)
    (root / "inventory.yaml").write_text(
        yaml.dump(
            {
                "tools": [
                    {
                        "id": "approve_loan",
                        "arguments": {"approved_amount": {"type": "number"}},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (policies_dir / "block.yaml").write_text(
        yaml.dump(
            {
                "id": "block-large",
                "trigger": {
                    "event": "before_tool_call",
                    "tool_id": "approve_loan",
                },
                "conditions": {
                    "field": "approved_amount",
                    "operator": ">",
                    "value": 1000,
                },
                "action": {"type": "block"},
            }
        ),
        encoding="utf-8",
    )
    (root / "openagentpolicy.yaml").write_text(
        yaml.dump(
            {
                "inventory": {"provider": "file", "path": "./inventory.yaml"},
                "policies": {
                    "provider": "directory",
                    "path": "./policies",
                    "compile_on_startup": True,
                },
            }
        ),
        encoding="utf-8",
    )

    runtime = PolicyRuntime.from_config(root / "openagentpolicy.yaml")
    assert runtime.inventory.tools[0].id == "approve_loan"
    assert len(runtime.policies) == 1
    assert runtime.policies[0].id == "block-large"
