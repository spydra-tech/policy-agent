from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from openagentpolicy import PolicyEngine
from openagentpolicy.cli.validate import (
    ValidationError,
    compile_policy_file,
    test_policy_against_event,
    validate_config_file,
    validate_inventory_file,
    validate_policy_file,
)
from openagentpolicy.traces.inventory_builder import TraceInventoryBuilder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="openagentpolicy",
        description="Policy enforcement CLI for openagentpolicy",
    )
    sub = parser.add_subparsers(dest="command")

    _add_validate_config(sub)
    _add_validate_inventory(sub)
    _add_validate_policy(sub)
    _add_compile_policy(sub)
    _add_test_policy(sub)
    _add_generate_inventory(sub)
    _add_check(sub)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    try:
        return _dispatch(args)
    except ValidationError as exc:
        for error in exc.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "validate-config":
        validate_config_file(args.config)
        print(f"OK: {args.config}")
        return 0

    if args.command == "validate-inventory":
        inventory = validate_inventory_file(args.inventory)
        print(f"OK: {args.inventory} ({len(inventory.tools)} tools)")
        return 0

    if args.command == "validate-policy":
        documents = validate_policy_file(args.policy, args.inventory)
        print(f"OK: {args.policy} ({len(documents)} policies)")
        return 0

    if args.command == "compile-policy":
        results = compile_policy_file(args.policy, args.inventory)
        print(yaml.safe_dump(results, sort_keys=False))
        return 0

    if args.command == "test-policy":
        output = test_policy_against_event(args.policy, args.event, args.inventory)
        print(json.dumps(output, indent=2))
        decision = output["decision"]["decision"]
        return 0 if decision == "allow" else 1

    if args.command == "generate-inventory":
        builder = TraceInventoryBuilder()
        inventory = builder.build_from_jsonl(args.traces)
        output = builder.write_yaml(inventory, args.output)
        print(f"Wrote generated inventory to {output}")
        print(
            f"Tools: {len(inventory.tools)}, "
            f"trace_count: {inventory.generated_from.trace_count}"
        )
        return 0

    if args.command == "check":
        engine = PolicyEngine.from_config(args.config)
        arguments = json.loads(args.args)
        result = engine.check_tool_call(args.tool, arguments)
        print(json.dumps(result.model_dump(), indent=2))
        return 0 if result.decision.value == "allow" else 1

    return 0


def _add_validate_config(sub: argparse._SubParsersAction) -> None:
    cmd = sub.add_parser("validate-config", help="Validate engine config YAML")
    cmd.add_argument("config", type=Path, help="Path to openagentpolicy.yaml")


def _add_validate_inventory(sub: argparse._SubParsersAction) -> None:
    cmd = sub.add_parser("validate-inventory", help="Validate inventory YAML")
    cmd.add_argument("inventory", type=Path, help="Path to inventory.yaml")


def _add_validate_policy(sub: argparse._SubParsersAction) -> None:
    cmd = sub.add_parser(
        "validate-policy", help="Validate policy file or directory"
    )
    cmd.add_argument(
        "policy",
        type=Path,
        help="Path to policy YAML/JSON or policies directory",
    )
    cmd.add_argument(
        "--inventory",
        type=Path,
        required=True,
        help="Path to inventory.yaml for cross-validation",
    )


def _add_compile_policy(sub: argparse._SubParsersAction) -> None:
    cmd = sub.add_parser(
        "compile-policy",
        help="Compile English or structured policies to enforceable form",
    )
    cmd.add_argument(
        "policy",
        type=Path,
        help="Path to policy YAML/JSON or policies directory",
    )
    cmd.add_argument(
        "--inventory",
        type=Path,
        required=True,
        help="Path to inventory.yaml used for English compilation",
    )


def _add_test_policy(sub: argparse._SubParsersAction) -> None:
    cmd = sub.add_parser(
        "test-policy", help="Evaluate a policy against a sample event"
    )
    cmd.add_argument(
        "policy",
        type=Path,
        help="Path to policy YAML/JSON or policies directory",
    )
    cmd.add_argument(
        "--event",
        type=Path,
        required=True,
        help="Path to event JSON/YAML (e.g. events/high_value_loan.json)",
    )
    cmd.add_argument(
        "--inventory",
        type=Path,
        required=True,
        help="Path to inventory.yaml",
    )


def _add_generate_inventory(sub: argparse._SubParsersAction) -> None:
    cmd = sub.add_parser(
        "generate-inventory",
        help="Generate inventory YAML from JSONL trace events",
    )
    cmd.add_argument(
        "--traces",
        type=Path,
        required=True,
        help="Path to JSONL trace file",
    )
    cmd.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output path for generated_inventory.yaml",
    )


def _add_check(sub: argparse._SubParsersAction) -> None:
    cmd = sub.add_parser(
        "check",
        help="Check a tool call using full engine config (legacy)",
    )
    cmd.add_argument("--config", required=True, help="Path to engine config")
    cmd.add_argument("--tool", required=True, help="Tool name")
    cmd.add_argument(
        "--args",
        default="{}",
        help="JSON object of tool arguments",
    )


if __name__ == "__main__":
    sys.exit(main())
