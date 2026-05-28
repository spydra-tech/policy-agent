from __future__ import annotations

from pathlib import Path
from typing import Any

from openagentpolicy.config import config_base_path, load_config
from openagentpolicy.compiler import compile_english_policy
from openagentpolicy.inventory.resolver import InventoryResolver
from openagentpolicy.inventory.providers import FileInventoryProvider
from openagentpolicy.inventory.schema import Inventory
from openagentpolicy.policies.compiler import PolicyCompiler
from openagentpolicy.policies.providers import DirectoryPolicyProvider, PolicyProvider, load_policy_file
from openagentpolicy.policies.schema import (
    CompileStatus,
    Condition,
    PolicyDocument,
    PolicyType,
    TriggerEvent,
)
from openagentpolicy.runtime.events import PolicyEvent
from openagentpolicy.runtime.policy_field_validation import validate_policy_fields


class ValidationError(Exception):
    """Raised when validation fails."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


def validate_config_file(path: Path) -> None:
    errors: list[str] = []
    try:
        load_config(path)
    except Exception as exc:
        errors.append(f"Invalid config: {exc}")
    if errors:
        raise ValidationError(errors)


def validate_inventory_file(path: Path) -> Inventory:
    errors: list[str] = []
    try:
        inventory = FileInventoryProvider(path).load()
    except Exception as exc:
        errors.append(f"Invalid inventory: {exc}")
        raise ValidationError(errors) from exc

    if not inventory.tools:
        errors.append("Inventory contains no tools")

    tool_ids: set[str] = set()
    for tool in inventory.tools:
        if tool.id in tool_ids:
            errors.append(f"Duplicate tool id: {tool.id}")
        tool_ids.add(tool.id)

    if errors:
        raise ValidationError(errors)
    return inventory


def load_policy_documents(path: Path) -> list[PolicyDocument]:
    if path.is_dir():
        return DirectoryPolicyProvider(path).load_documents()
    return load_policy_file(path)


def validate_policy_file(path: Path, inventory_path: Path) -> list[PolicyDocument]:
    errors: list[str] = []
    inventory = validate_inventory_file(inventory_path)
    documents = load_policy_documents(path)

    if not documents:
        errors.append(f"No policies found at {path}")

    compiler = PolicyCompiler(inventory)
    for document in documents:
        if document.policy_type == PolicyType.ENGLISH:
            result = compiler.compile_document(document)
            if result.compile_status != CompileStatus.COMPILED:
                errors.append(
                    f"Policy {document.id}: not enforceable "
                    f"({result.message}); missing_fields={result.missing_fields}"
                )
            continue

        try:
            policy = document.to_policy()
        except Exception as exc:
            errors.append(f"Policy {document.id}: {exc}")
            continue

        if policy.trigger and policy.trigger.tool_id:
            tool = inventory.get_tool(policy.trigger.tool_id)
            if tool is None:
                errors.append(
                    f"Policy {document.id}: unknown tool_id "
                    f"{policy.trigger.tool_id!r}"
                )
            elif policy.conditions:
                errors.extend(
                    _validate_conditions(
                        document.id,
                        policy.conditions,
                        tool,
                    )
                )

    if errors:
        raise ValidationError(errors)
    return documents


def compile_policy_file(path: Path, inventory_path: Path) -> list[dict[str, Any]]:
    inventory = validate_inventory_file(inventory_path)
    documents = load_policy_documents(path)
    compiler = PolicyCompiler(inventory)
    outputs: list[dict[str, Any]] = []
    for document in documents:
        result = compiler.compile_document(document)
        outputs.append(result.model_dump(mode="json", exclude_none=True))
    return outputs


def explain_config(path: Path) -> dict[str, Any]:
    config = load_config(path)
    base_path = config_base_path(path)
    inventory = InventoryResolver(config.inventory, base_path).preload()
    provider = PolicyProvider(config.policies, base_path, inventory=inventory)
    loaded_policies, compile_results = provider.load_policies_with_results()
    mismatches = validate_policy_fields(loaded_policies, inventory)

    compiled: list[dict[str, Any]] = []
    unenforceable: list[dict[str, Any]] = []
    for result in compile_results:
        item = {
            "policy_id": result.policy_id,
            "compile_status": result.compile_status.value,
            "confidence": result.confidence,
            "message": result.message,
            "missing_fields": result.missing_fields,
        }
        if result.compile_status == CompileStatus.COMPILED:
            compiled.append(item)
        else:
            unenforceable.append(item)

    return {
        "config_path": str(path.resolve()),
        "inventory": {
            "tool_count": len(inventory.tools),
            "agent_count": len(inventory.agents),
        },
        "loaded_policies": [policy.id for policy in loaded_policies],
        "compiled_policies": compiled,
        "unenforceable_policies": unenforceable,
        "inventory_mismatches": [issue.format() for issue in mismatches],
    }


def compile_english_to_policy(
    *,
    english: str,
    inventory_path: Path,
    policy_id: str | None = None,
    action_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inventory = validate_inventory_file(inventory_path)
    result = compile_english_policy(
        english=english,
        inventory=inventory,
        policy_id=policy_id,
        action_hint=action_hint,
    )
    return result.model_dump(mode="json")


def explain_policy_file(path: Path, inventory_path: Path) -> dict[str, Any]:
    inventory = validate_inventory_file(inventory_path)
    documents = load_policy_documents(path)
    compiler = PolicyCompiler(inventory)
    details: list[dict[str, Any]] = []
    for document in documents:
        if document.policy_type == PolicyType.ENGLISH:
            result = compiler.compile_document(document)
            details.append(
                {
                    "policy_id": document.id,
                    "policy_type": document.policy_type.value,
                    "compile_status": result.compile_status.value,
                    "resolved_terms": result.resolved_terms,
                    "missing_fields": result.missing_fields,
                    "message": result.message,
                }
            )
        else:
            policy = document.to_policy()
            errors = _validate_conditions(document.id, policy.conditions, inventory.get_tool(policy.trigger.tool_id) if policy.trigger and policy.trigger.tool_id else None) if policy.conditions and policy.trigger and policy.trigger.tool_id else []
            details.append(
                {
                    "policy_id": document.id,
                    "policy_type": document.policy_type.value,
                    "enforceability": "enforceable" if not errors else "not_enforceable",
                    "errors": errors,
                }
            )
    return {"policies": details}


def test_policy_against_event(
    path: Path, event_path: Path, inventory_path: Path
) -> dict[str, Any]:
    inventory = validate_inventory_file(inventory_path)
    documents = load_policy_documents(path)
    compiler = PolicyCompiler(inventory)

    policies = []
    for document in documents:
        result = compiler.compile_document(document)
        if result.compiled_policy is not None:
            policies.append(result.compiled_policy)
        else:
            try:
                policies.append(document.to_policy())
            except ValueError:
                pass

    if not policies:
        raise ValidationError([f"No enforceable policies loaded from {path}"])

    event = _load_event_file(event_path)

    from openagentpolicy.runtime.evaluator import (
        PolicyEvaluator,
        build_evaluation_context,
    )

    evaluator = PolicyEvaluator()
    trigger = TriggerEvent(event.event_type)
    decision = evaluator.evaluate(
        event.tool_id or "",
        build_evaluation_context(
            tool_args=event.tool_args,
            tool_result=event.tool_result,
            tool={},
            metadata=event.metadata,
            final_response=event.final_response,
            agent_id=event.agent_id,
        ),
        policies,
        trigger_event=trigger,
        agent_id=event.agent_id,
    )
    return {
        "event": event.model_dump(mode="json"),
        "decision": decision.model_dump(mode="json"),
    }


def _load_event_file(path: Path) -> PolicyEvent:
    import json

    import yaml

    text = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return PolicyEvent.model_validate(data)


def _validate_conditions(
    policy_id: str, condition: Condition, tool: Any
) -> list[str]:
    errors: list[str] = []
    if condition.is_leaf:
        errors.extend(_validate_field(policy_id, condition.field, tool))
    if condition.all:
        for child in condition.all:
            errors.extend(_validate_conditions(policy_id, child, tool))
    if condition.any:
        for child in condition.any:
            errors.extend(_validate_conditions(policy_id, child, tool))
    if condition.not_:
        errors.extend(_validate_conditions(policy_id, condition.not_, tool))
    return errors


def _validate_field(policy_id: str, field: str | None, tool: Any) -> list[str]:
    if not field:
        return []
    arg_name = field.removeprefix("tool_args.")
    if field.startswith("tool_result.") or field == "final_response":
        return []
    if field.startswith("metadata."):
        return []
    if arg_name not in tool.arguments and not field.startswith("tool_args."):
        return [
            f"Policy {policy_id}: field {field!r} not found on tool {tool.id!r}"
        ]
    if field.startswith("tool_args.") and arg_name not in tool.arguments:
        return [
            f"Policy {policy_id}: argument {arg_name!r} not in tool {tool.id!r}"
        ]
    return []
