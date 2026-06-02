# Agentic insurance claims (CrewAI)

Scripted demo of **English and structured policies** on an **insurance claims** workflow
with a **CrewAI** crew shape: adjuster intake → fraud review → payout. Tools are wrapped
as CrewAI `BaseTool` instances that call `@policy_tool` functions under the correct
`agent_id` via `agent_session`.

Distinct from [agentic_procurement](../agentic_procurement/) (payables) and
[agentic_stock_research](../agentic_stock_research/) (LangGraph). The primary path is
`demo.py` (no LLM); optional `python demo.py --crew` runs a real `Crew.kickoff()` when
`OPENAI_API_KEY` is set.

## Agents and tools

| Agent | Role |
|-------|------|
| `claims-adjuster-agent` | Policy lookup and claim intake |
| `fraud-analyst-agent` | Fraud flags; must not issue payouts |
| `payout-agent` | Issues claim payouts when metadata allows |
| `customer-service-agent` | Status only; no intake or payout |

| Tool | Risk | Purpose |
|------|------|---------|
| `lookup_policy` | low | Mock policy lookup |
| `record_claim_intake` | medium | Register a new claim |
| `flag_fraud_signal` | medium | Add a fraud review flag |
| `issue_claim_payout` | high | Issue payment on a claim |

## Policy ladder

| File | Type | What it proves |
|------|------|----------------|
| `01_block_large_total_loss_payout_english.yaml` | English | Blocks large total-loss payouts |
| `02_only_payout_agent_may_pay_english.yaml` | English | Only `payout-agent` may pay |
| `03_supervisor_approval_required.yaml` | Structured | Payouts > $15k need `metadata.supervisor_approved: true` |
| `04_block_claim_fully_approved_response.yaml` | Structured | Blocks “claim fully approved” in final text |
| `05_only_adjuster_may_intake_english.yaml` | English | Only `claims-adjuster-agent` may record intake |

## Run

```bash
pip install -e ".[dev]"   # from repo root
pip install -r requirements.txt   # CrewAI (optional for --crew)
cd examples/agentic_insurance_claims
python demo.py
```

Optional live crew (requires `OPENAI_API_KEY` and `crewai`):

```bash
export OPENAI_API_KEY=sk-...
python demo.py --crew
```

## Integration points

| File | Role |
|------|------|
| `tools.py` | `@policy_tool` on each claims action |
| `crew_tools.py` | CrewAI tools → `run_as_agent(agent_id, fn, ...)` |
| `crew.py` | `Agent` / `Task` / `Crew` definitions |
| `agent_session.py` | `run_as_agent`, `run_crew_role`, `finalize_response` |
| `demo.py` | `configure()` then scripted scenarios + optional crew |
| `policies/` | Rules owned by compliance, not Python `if` branches |

Traces: `openagentpolicy_traces/events.jsonl`

## Compile a policy

```bash
openagentpolicy compile-policy policies/01_block_large_total_loss_payout_english.yaml --inventory inventory.yaml
```
