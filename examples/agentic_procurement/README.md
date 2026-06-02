# Agentic procurement desk

Scripted demo of **English and structured policies** on a **procurement / payables** workflow:
purchase orders, vendor payments, role separation, and session metadata for budget sign-off.

Distinct from [agentic_loan_desk](../agentic_loan_desk/) (lending) and
[agentic_stock_research](../agentic_stock_research/) (markets + LangGraph). This example uses a
**custom orchestrator** (`demo.py`) so the integration pattern is easy to read.

## Agents and tools

| Agent | Role |
|-------|------|
| `requester-agent` | Business user; may look up vendors but cannot create POs (policy-gated) |
| `procurement-agent` | Creates POs; may approve payments when metadata allows |
| `finance-agent` | Read-only spend review; must not approve payments or create POs |

| Tool | Risk | Purpose |
|------|------|---------|
| `lookup_vendor` | low | Mock vendor lookup |
| `create_purchase_order` | medium | Create a PO |
| `approve_vendor_payment` | high | Approve payment on a PO |

## Policy ladder

| File | Type | What it proves |
|------|------|----------------|
| `01_block_large_equipment_po_english.yaml` | English | Blocks equipment POs over $25k |
| `02_only_procurement_may_approve_payment_english.yaml` | English | Only `procurement-agent` may pay |
| `03_budget_holder_approval_required.yaml` | Structured | Payments > $10k need `metadata.budget_holder_approved: true` |
| `04_block_guaranteed_savings_response.yaml` | Structured | Blocks “guaranteed savings” in final text |
| `05_only_procurement_may_create_po_english.yaml` | English | Only `procurement-agent` may create POs |

## Run

```bash
pip install -e ".[dev]"   # from repo root
cd examples/agentic_procurement
python demo.py
```

## Integration points (for your own app)

| File | Role |
|------|------|
| `tools.py` | `@policy_tool` on each ERP action |
| `agent_session.py` | `run_as_agent` + `finalize_response` |
| `demo.py` | `configure()` then scripted scenarios |
| `policies/` | Rules owned by compliance, not Python `if` branches |

Traces: `openagentpolicy_traces/events.jsonl`

## Compile a policy

```bash
openagentpolicy compile-policy policies/01_block_large_equipment_po_english.yaml --inventory inventory.yaml
```
