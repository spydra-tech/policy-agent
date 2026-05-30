# Agentic stock research (LangGraph)

End-to-end demo of **English policies** on a **LangGraph** workflow for equity research and trading controls. This example is separate from [agentic_loan_desk](../agentic_loan_desk/): different domain (markets vs loans), different agents/tools, and a real LangGraph `StateGraph` instead of a hand-rolled orchestrator.

## What it shows

| Tier | Scope | Policy | Behavior |
|------|-------|--------|----------|
| Tool | English | `01_block_large_order_english.yaml` | Blocks orders with quantity > 100 |
| Agent + tool | English | `02_only_trading_desk_may_trade_english.yaml` | Only `trading-desk-agent` may call `place_trade_order` |
| Workflow | Structured | `03_compliance_clearance_required.yaml` | Trades require `metadata.compliance_cleared: true` |
| Agent output | Structured | `04_block_guaranteed_returns_response.yaml` | Blocks “guaranteed returns” in final text |
| Agent + tool | English | `05_retail_no_save_note_english.yaml` | Only `research-agent` may call `save_research_note` |

## Prerequisites

From the repository root:

```bash
pip install -e ".[dev]"
pip install -r examples/agentic_stock_research/requirements.txt
```

## Run the demo

```bash
cd examples/agentic_stock_research
python demo.py
```

Phases:

1. **Compile** sample English policies (CLI, rule-based).
2. **LangGraph research** — `research-agent` runs read-only tools (`get_stock_quote`, `search_financial_news`) inside `agent_session`.
3. **Trade scenarios** — policy blocks for wrong agent, missing compliance, oversized order, then a small allowed trade.
4. **Note policy** — `retail-copilot-agent` blocked from `save_research_note`.
5. **Final response** — structured guard on user-visible text.

Traces are written to `openagentpolicy_traces/events.jsonl`.

## LangGraph integration

`graph.py` defines a small `StateGraph`:

```text
START → gather (quote + news) → [note | trade | report] → END
```

- Tool calls run inside `with_agent_session(state)` so `@policy_tool` enforcement applies.
- `demo.py` calls `finalize_graph_output()` after the graph to run `before_final_response` policies (same pattern as the root README’s LangGraph example).

There is **no live LLM or broker API** — quotes and news are mocked so the demo runs offline.

## Files

| File | Purpose |
|------|---------|
| `openagentpolicy.yaml` | Runtime config (`english_compiler: hybrid`) |
| `inventory.yaml` | Agents, tools, argument aliases for the compiler |
| `policies/` | English + structured policies |
| `tools.py` | `@policy_tool` definitions |
| `graph.py` | LangGraph workflow |
| `agent_session.py` | Session + final-response helpers |
| `demo.py` | Scripted scenarios |
| `requirements.txt` | `langgraph`, `langchain-core` |

## Inspect policies

```bash
openagentpolicy compile-policy policies/01_block_large_order_english.yaml --inventory inventory.yaml
openagentpolicy explain --config openagentpolicy.yaml --format json
```
