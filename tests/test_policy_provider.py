from pathlib import Path

import pytest
import yaml

from openagentpolicy.config import PoliciesConfig, resolve_config_path
from openagentpolicy.policies.compiler import PolicyCompiler
from openagentpolicy.policies.providers import (
    DirectoryPolicyProvider,
    FilePolicyProvider,
    HTTPPolicyProvider,
    PolicyProvider,
    create_policy_source_provider,
)
from openagentpolicy.policies.schema import (
    ActionType,
    CompileStatus,
    ConditionOperator,
    PolicyDocument,
    PolicyType,
)
from openagentpolicy.policies.schema import TriggerEvent
from openagentpolicy.runtime.decisions import DecisionType
from openagentpolicy.runtime.evaluator import PolicyEvaluator


def test_file_policy_provider_loads_single_yaml(tmp_path: Path) -> None:
    doc = {
        "id": "limits",
        "trigger": {"event": "before_tool_call", "tool_id": "approve_loan"},
        "conditions": {"field": "amount", "operator": ">", "value": 10000},
        "action": {"type": "block", "message": "Too large"},
    }
    path = tmp_path / "limits.yaml"
    path.write_text(yaml.dump(doc), encoding="utf-8")

    documents = FilePolicyProvider(path).load_documents()
    assert len(documents) == 1
    assert documents[0].id == "limits"


def test_directory_policy_provider_loads_all_policy_files(tmp_path: Path) -> None:
    policies_dir = tmp_path / "policies"
    policies_dir.mkdir()
    (policies_dir / "alpha.yaml").write_text(
        yaml.dump(
            {
                "id": "alpha",
                "trigger": {"event": "before_tool_call"},
                "conditions": {"field": "metadata.trace_id", "operator": "exists"},
                "action": {"type": "allow"},
            }
        ),
        encoding="utf-8",
    )
    (policies_dir / "beta.json").write_text(
        '{"id": "beta", "trigger": {"event": "before_tool_call"}, "conditions": {"field": "metadata.trace_id", "operator": "exists"}, "action": {"type": "log_only"}}',
        encoding="utf-8",
    )
    (policies_dir / "ignored.txt").write_text("skip", encoding="utf-8")

    documents = DirectoryPolicyProvider(policies_dir).load_documents()
    assert {doc.id for doc in documents} == {"alpha", "beta"}


def test_create_directory_policy_provider_resolves_relative_path(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "app"
    policies_dir = config_dir / "policies"
    policies_dir.mkdir(parents=True)
    (policies_dir / "one.yaml").write_text(
        yaml.dump(
            {
                "id": "one",
                "trigger": {"event": "before_tool_call"},
                "conditions": {"field": "metadata.trace_id", "operator": "exists"},
                "action": {"type": "allow"},
            }
        ),
        encoding="utf-8",
    )

    provider = create_policy_source_provider(
        PoliciesConfig(provider="directory", path="./policies"),
        config_dir,
    )
    documents = provider.load_documents()
    assert documents[0].id == "one"
    assert resolve_config_path(config_dir, "./policies") == policies_dir.resolve()


def test_policy_provider_loads_and_compiles_directory(tmp_path: Path) -> None:
    policies_dir = tmp_path / "policies"
    policies_dir.mkdir()
    (policies_dir / "limits.yaml").write_text(
        yaml.dump(
            {
                "id": "limits",
                "trigger": {"event": "before_tool_call", "tool_id": "approve_loan"},
                "conditions": {
                    "field": "amount",
                    "operator": ">",
                    "value": 10000,
                },
                "action": {"type": "block"},
            }
        ),
        encoding="utf-8",
    )

    provider = PolicyProvider(
        PoliciesConfig(provider="directory", path="policies"),
        tmp_path,
    )
    policies = provider.load_policies()
    assert len(policies) == 1
    assert policies[0].action is not None
    assert policies[0].action.type == ActionType.BLOCK


def test_policy_provider_loads_legacy_rules_yaml(tmp_path: Path) -> None:
    policies_dir = tmp_path / "policies"
    policies_dir.mkdir()
    doc = {
        "id": "limits",
        "rules": [
            {
                "id": "cap",
                "tool": "approve_loan",
                "effect": "deny",
                "conditions": {"amount": {"gt": 10000}},
            }
        ],
    }
    (policies_dir / "limits.yaml").write_text(
        yaml.dump(doc), encoding="utf-8"
    )

    provider = PolicyProvider(
        PoliciesConfig(provider="directory", path="policies"),
        tmp_path,
    )
    policies = provider.load_policies()
    assert len(policies) == 1
    assert policies[0].id == "cap"


def test_http_policy_provider_requires_requests() -> None:
    provider = HTTPPolicyProvider("https://example.com/policies.yaml")
    with pytest.raises(ImportError, match="requests"):
        provider.load_documents()


def test_compiler_parses_english_with_inventory() -> None:
    from openagentpolicy.inventory.schema import ArgumentSchema, Inventory, Tool

    inventory = Inventory(
        tools=[
            Tool(
                id="approve_loan",
                arguments={
                    "risk_score": ArgumentSchema(
                        type="number", aliases=["risk score"]
                    ),
                },
            )
        ]
    )
    compiler = PolicyCompiler(inventory)
    document = PolicyDocument(
        id="english_policy",
        policy_type=PolicyType.ENGLISH,
        english="If risk score is greater than 0.7, approval is not allowed.",
        hints={"action": {"type": "block"}},
    )
    result = compiler.compile_document(document)
    assert result.compile_status == CompileStatus.COMPILED
    assert result.compiled_policy is not None
    policy = result.compiled_policy
    assert policy.trigger is not None
    assert policy.trigger.tool_id == "approve_loan"
    assert policy.conditions is not None
    assert policy.conditions.operator == ConditionOperator.GT
    assert policy.conditions.value == 0.7
