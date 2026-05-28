from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from openagentpolicy.runtime.engine import PolicyRuntime


def _write_fixture(
    tmp_path: Path,
    *,
    environment: str,
    fail_on_unenforceable: bool,
    english_policy: dict,
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
                            "approval_mode": {
                                "type": "string",
                                "allowed_values": ["auto", "manual"],
                            },
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (policies_dir / "policy.yaml").write_text(
        yaml.dump(english_policy), encoding="utf-8"
    )
    (root / "openagentpolicy.yaml").write_text(
        yaml.dump(
            {
                "application": {
                    "id": "loan-app",
                    "environment": environment,
                },
                "inventory": {"provider": "file", "path": "./inventory.yaml"},
                "policies": {
                    "provider": "directory",
                    "path": "./policies",
                    "support_english": True,
                    "compile_on_startup": True,
                },
                "enforcement": {
                    "default_action": "allow",
                    "fail_on_unenforceable": fail_on_unenforceable,
                },
            }
        ),
        encoding="utf-8",
    )
    return root / "openagentpolicy.yaml"


def test_fail_on_unenforceable_blocks_startup_in_production(tmp_path: Path) -> None:
    config = _write_fixture(
        tmp_path,
        environment="production",
        fail_on_unenforceable=True,
        english_policy={
            "id": "kyc_policy",
            "policy_type": "english",
            "english": "If KYC tier is high, block.",
        },
    )
    with pytest.raises(ValueError, match="unenforceable"):
        PolicyRuntime.from_config(config)


def test_fail_on_unenforceable_does_not_block_non_production(tmp_path: Path) -> None:
    config = _write_fixture(
        tmp_path,
        environment="development",
        fail_on_unenforceable=True,
        english_policy={
            "id": "kyc_policy",
            "policy_type": "english",
            "english": "If KYC tier is high, block.",
        },
    )
    runtime = PolicyRuntime.from_config(config)
    assert runtime is not None


def test_fail_on_unenforceable_false_allows_production_startup(tmp_path: Path) -> None:
    config = _write_fixture(
        tmp_path,
        environment="production",
        fail_on_unenforceable=False,
        english_policy={
            "id": "kyc_policy",
            "policy_type": "english",
            "english": "If KYC tier is high, block.",
        },
    )
    runtime = PolicyRuntime.from_config(config)
    assert runtime is not None
