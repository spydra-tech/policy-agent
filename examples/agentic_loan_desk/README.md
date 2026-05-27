# Agentic loan desk example

End-to-end demo of **English policies compiled and enforced** at both **tool** and **agent** scope. No LLM is required — scenarios are scripted in `demo.py`.

For a minimal tool-only introduction, see [loan_approval_basic](../loan_approval_basic/).

## Prerequisites

From the repository root:

```bash
pip install -e ".[dev]"
```

## Policy ladder

| Tier | Scope | File | What it proves |
|------|-------|------|----------------|
| Easy | Tool | `policies/01_tool_high_value_english.yaml` | English compiles via inventory; blocks large **auto** approvals |
| Easy (ref) | Tool | `policies/01_tool_high_value_structured.yaml` | Same rule in structured form (disabled) |
| Medium | Agent + tool | `policies/02_agent_only_loan_agent_english.yaml` | Only `loan-agent` may call `approve_loan` |
| Medium+ | Agent workflow | `policies/03_workflow_human_review.yaml` | Large approvals need `metadata.human_reviewed: true` |
| Medium | Agent output | `policies/04_agent_safe_response.yaml` | Blocks unsafe guarantee language before the response is sent |

## English → enforceable policy

Inspect compilation without running the app:

```bash
cd examples/agentic_loan_desk
openagentpolicy compile-policy policies/01_tool_high_value_english.yaml --inventory inventory.yaml
openagentpolicy compile-policy policies/02_agent_only_loan_agent_english.yaml --inventory inventory.yaml
```

At runtime, enabled English policies are compiled in memory when `configure()` loads config (`support_english: true`, `compile_on_startup: true`). Only **compiled** structured policies are enforced.

## Run the demo

```bash
cd examples/agentic_loan_desk
python demo.py
```

You should see:

1. **Phase 1** — compiled triggers/conditions for English policies  
2. **Scenarios A–E** — labeled `ALLOWED` / `BLOCKED` with policy messages  
3. **Traces** — `openagentpolicy_traces/events.jsonl` audit log  

## How agents are modeled

`agent_session.py` wraps `openagentpolicy.agent_session` so each tool call carries:

- `agent_id` — which agent is acting (`loan-agent` vs `compliance-agent`)
- `metadata` — session flags such as `human_reviewed`

`finalize_response()` runs `before_final_response` policies on agent text.

## Architecture

```mermaid
flowchart TB
  subgraph author [Authoring]
    EN[English YAML]
    ST[Structured YAML]
  end
  subgraph compile [Compile]
    CLI[compile-policy CLI]
    Boot[Startup PolicyProvider]
  end
  subgraph runtime [Runtime]
    Session[agent_session]
    Tools[policy_tool wrappers]
    Resp[check_final_response]
    Eval[PolicyEvaluator]
  end
  EN --> CLI
  EN --> Boot
  ST --> Boot
  Boot --> Eval
  Session --> Tools
  Session --> Resp
  Tools --> Eval
  Resp --> Eval
```

## Files

| File | Purpose |
|------|---------|
| `openagentpolicy.yaml` | Runtime config, policy directory, traces |
| `inventory.yaml` | Agents, tools, argument aliases for the compiler |
| `policies/` | Tiered policies (English + structured) |
| `tools.py` | `@policy_tool` definitions |
| `agent_session.py` | Agent context helpers |
| `demo.py` | Scripted scenarios |
