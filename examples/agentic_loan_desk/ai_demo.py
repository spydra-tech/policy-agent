"""Minimal AI-mode demo: compile English policies with an LLM, then enforce them.

This is the smallest end-to-end path for "use AI for policy, then invoke a
request that tests different policies":

1. ``configure()`` loads ``openagentpolicy.ai.yaml`` (english_compiler: ai). This
   is the ONLY place the LLM translator runs -- English policies are compiled to
   structured policies here, and only those are enforced. (The CLI ``compile-*``
   commands and ``compile_english_policy()`` use the rule-based compiler instead.)
2. We print the policies the runtime actually loaded so you can see the
   English -> structured result.
3. We fire a few tool calls / a final-response check that exercise the different
   policy classes (tool threshold, agent allowlist, output guard).

Run:
    pip install openai
    export OPENAI_API_KEY=sk-...
    cd examples/agentic_loan_desk
    python ai_demo.py

Note on AI safety: AI output is auto-``compiled`` only when the deterministic
rule-based compiler independently produces an equivalent policy (corroboration).
Uncorroborated output is ``needs_review`` and is NOT enforced -- so keep English
phrasing within forms the rule grammar also understands (the bundled policies
are), or those policies simply will not load.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from openagentpolicy import configure, get_runtime
from openagentpolicy.annotations import PolicyViolation

from agent_session import finalize_response, run_as_agent
from tools import approve_loan

EXAMPLE_DIR = Path(__file__).parent
AI_CONFIG = EXAMPLE_DIR / "openagentpolicy.ai.yaml"


def _print_header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print("=" * 60)


def _show_loaded_policies() -> None:
    """Print what the runtime actually compiled and will enforce."""
    runtime = get_runtime()
    policies = runtime.policies
    if not policies:
        print("No enforceable policies loaded. In ai mode this usually means the")
        print("LLM output was not corroborated (needs_review) or the key/SDK is")
        print("missing. Run `openagentpolicy explain --config openagentpolicy.ai.yaml`.")
        return
    for policy in policies:
        trigger = policy.trigger
        print(f"\n- {policy.id} ({policy.policy_type.value})")
        if trigger is not None:
            print(
                f"    trigger: event={trigger.event.value!r} "
                f"tool_id={trigger.tool_id!r} agent_id={trigger.agent_id!r}"
            )
        if policy.conditions is not None:
            print(f"    conditions: {json.dumps(policy.conditions.model_dump(exclude_none=True))}")
        if policy.action is not None:
            print(f"    action: {policy.action.type.value}")
        if policy.source and policy.source.get("english"):
            print(f"    from english: {policy.source['english'].strip()!r}")


def _run_tool_scenario(
    label: str,
    agent_id: str,
    fn: Callable[..., Any],
    /,
    *,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    print(f"\n--- {label} ---")
    arg_preview = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    print(f"agent={agent_id!r}  call={fn.__name__}({arg_preview})")
    try:
        result = run_as_agent(agent_id, fn, metadata=metadata, **kwargs)
        print(f"Result: ALLOWED -> {result}")
    except PolicyViolation as exc:
        print(f"Result: BLOCKED -> {exc}")
        if exc.decision and exc.decision.matched_policies:
            print(f"  matched_policies={exc.decision.matched_policies}")


def _run_response_scenario(label: str, agent_id: str, text: str) -> None:
    print(f"\n--- {label} ---")
    print(f"agent={agent_id!r}  response={text!r}")
    try:
        finalize_response(text, agent_id=agent_id)
        print("Result: ALLOWED")
    except PolicyViolation as exc:
        print(f"Result: BLOCKED -> {exc}")


def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        print(
            "WARNING: OPENAI_API_KEY is not set. In `ai` mode the translator "
            "returns nothing, so English policies will be needs_review and will "
            "NOT be enforced. Set the key (and `pip install openai`) to exercise "
            "the LLM path."
        )

    _print_header("Loading runtime (english_compiler: ai)")
    configure(AI_CONFIG)
    print("Policies the runtime compiled and will enforce:")
    _show_loaded_policies()

    _print_header("Tool threshold policy (compiled from English)")
    _run_tool_scenario(
        "loan-agent, $4k auto (expected: ALLOW)",
        "loan-agent",
        approve_loan,
        application_id="app-3001",
        approved_amount=4000,
        approval_mode="auto",
    )
    _run_tool_scenario(
        "loan-agent, $7k auto (expected: BLOCK)",
        "loan-agent",
        approve_loan,
        application_id="app-3002",
        approved_amount=7000,
        approval_mode="auto",
    )

    _print_header("Agent allowlist policy (compiled from English)")
    _run_tool_scenario(
        "compliance-agent, $4k auto (expected: BLOCK)",
        "compliance-agent",
        approve_loan,
        application_id="app-3003",
        approved_amount=4000,
        approval_mode="auto",
    )

    _print_header("Final-response guard (structured)")
    _run_response_scenario(
        "unsafe guarantee language (expected: BLOCK)",
        "loan-agent",
        "We offer guaranteed approval on all applications.",
    )
    _run_response_scenario(
        "safe response (expected: ALLOW)",
        "loan-agent",
        "Your application is under review; we will respond within two business days.",
    )


if __name__ == "__main__":
    main()
