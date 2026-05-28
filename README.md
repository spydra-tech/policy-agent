# openagentpolicy

Policy enforcement runtime for AI and agentic applications. Add `@policy_tool` to tool functions, load inventory/policies from files or HTTP services, and enforce rules at runtime for tool calls and final responses.

See:
- [examples/loan_approval_basic](examples/loan_approval_basic/) for a minimal tool-only sample.
- [examples/agentic_loan_desk](examples/agentic_loan_desk/) for English-to-structured compilation, tool-level and agent-level enforcement, and response policies.

## Why This Is Needed

Agentic applications usually fail in predictable ways:
- A tool is called with valid syntax but risky business intent (for example, approving a high-value loan in auto mode).
- Different agents share the same tool, but not the same permissions.
- The final user message contains risky claims ("guaranteed approval"), even when tool usage was compliant.
- Rules exist in docs/confluence but are not enforced uniformly in runtime code.

`openagentpolicy` solves this by making policy checks part of execution, not just guidance:
- Tool guardrails enforce constraints at `before_tool_call` / `after_tool_call`.
- Agent context (`agent_id`, `metadata`) supports role- and workflow-based controls.
- Final response checks enforce communication policy before user-visible output.
- English policy authoring can be compiled to structured enforceable rules.

### Practical value examples

#### Example A: Prevent a costly automation mistake

Without policy:
- Agent calls `approve_loan(approved_amount=7500, approval_mode="auto")`
- Tool succeeds
- Business rule violated

With policy:
- Policy blocks `approved_amount > 5000` when mode is `auto`
- Runtime raises `PolicyViolation`
- Agent must escalate to review flow

#### Example B: Shared tools, role-specific control

Without policy:
- `compliance-agent` and `loan-agent` both can call `approve_loan`
- Access control must be reimplemented in each orchestrator path

With policy:
- One policy states only `loan-agent` may approve
- Any non-allowed agent is blocked consistently across frameworks

#### Example C: Safe communication after successful tools

Without response policy:
- Tool calls are compliant, but final answer says "guaranteed approval"
- Regulatory or trust risk at user boundary

With response policy:
- `before_final_response` catches banned language
- App returns safe fallback text or revised response

### Business and engineering benefits

- Fewer duplicated guardrail checks across services and frameworks
- Faster policy updates (file or API source + runtime reload)
- Better auditability (policy decisions appear in traces/audit logs)
- Safer multi-agent scaling because controls are centralized

## Quickstart

```bash
pip install -e ".[dev]"
```

```python
from openagentpolicy import configure, policy_tool

configure("openagentpolicy.yaml")

@policy_tool(id="approve_loan", risk_level="high", side_effect=True)
def approve_loan(application_id: str, approved_amount: float):
    return {"status": "approved", "application_id": application_id}
```

## How It Fits Agent Frameworks

`openagentpolicy` is framework-agnostic. You keep your existing framework and add policy hooks at boundaries:
- Tool boundary: decorate callable tools with `@policy_tool`.
- Agent boundary: wrap a run/turn with `agent_session(agent_id, metadata=...)`.
- Output boundary: call `check_final_response(...)` or `check_final_response_any(...)` before returning user-visible text.

### Custom orchestrator

```python
from openagentpolicy import agent_session, check_final_response

def run_turn(agent_id: str, session_meta: dict, messages: list[str]) -> str:
    with agent_session(agent_id, metadata=session_meta):
        draft = agent_generate_reply(messages)
    return check_final_response(draft)
```

### LangGraph / LangChain style

```python
from openagentpolicy import agent_session, check_final_response_any

def invoke_graph(graph, state: dict) -> dict:
    with agent_session(state["agent_id"], metadata=state.get("metadata", {})):
        out = graph.invoke(state)
    out["final_message"] = check_final_response_any(out["final_message"])
    return out
```

### Crew-style multi-agent run

```python
from openagentpolicy import agent_session

def run_agent(agent, task: str, metadata: dict) -> str:
    with agent_session(agent.id, metadata=metadata):
        return agent.run(task)  # tools called inside remain policy-enforced
```

## Configuration

```yaml
application:
  id: my_app
  environment: production

runtime:
  default_agent_id: loan-agent

inventory:
  provider: file
  path: ./inventory.yaml

policies:
  provider: directory
  path: ./policies
  support_english: true
  compile_on_startup: true

traces:
  enabled: true
  store:
    provider: local
    path: ./openagentpolicy_traces

enforcement:
  default_action: allow
  on_policy_error: allow_with_warning
  audit_enabled: true
```

## Inventory: File and API Examples

### Static file inventory (`inventory.provider: file`)

```yaml
application:
  id: loan-approval-app
  name: Loan Approval App
  environment: demo

agents:
  - id: loan-agent
    name: Loan Agent
  - id: compliance-agent
    name: Compliance Agent

tools:
  - id: approve_loan
    name: Approve Loan
    risk_level: high
    side_effect: true
    arguments:
      approved_amount:
        type: number
        aliases: [approved amount]
      approval_mode:
        type: string
        allowed_values: [auto, manual]
  - id: send_to_human_review
    name: Send to Human Review
    risk_level: medium
    side_effect: true
    arguments:
      reason:
        type: string
```

### Dynamic inventory from API (`inventory.provider: http`)

```yaml
inventory:
  provider: http
  url: https://policy-service.example.com/v1/inventory
```

Expected API response shape (JSON or YAML body):

```json
{
  "agents": [{"id": "loan-agent"}],
  "tools": [
    {
      "id": "approve_loan",
      "arguments": {
        "approved_amount": {"type": "number"}
      }
    }
  ]
}
```

## Policies: File and API Examples

### Static policy directory (`policies.provider: directory`)

```yaml
policies:
  provider: directory
  path: ./policies
```

### Single policy file (`policies.provider: file`)

```yaml
policies:
  provider: file
  path: ./policies/auto_approval.yaml
```

### Dynamic policies from API (`policies.provider: http`)

```yaml
policies:
  provider: http
  url: https://policy-service.example.com/v1/policies
  support_english: true
```

Expected API response can be one policy object or an array of policy objects (same schema as local policy YAML files).

To refresh policies after an API-side update:

```python
from openagentpolicy import get_runtime

get_runtime().reload()
```

## Policy Ladder: Simple to Complex

### 1) Simple tool threshold (structured)

```yaml
id: block_large_auto
enabled: true
policy_type: structured
trigger:
  event: before_tool_call
  tool_id: approve_loan
conditions:
  all:
    - field: tool_args.approved_amount
      operator: ">"
      value: 5000
    - field: tool_args.approval_mode
      operator: "=="
      value: auto
action:
  type: block
  message: Auto approval is not allowed above 5000.
```

### 2) Same rule in English (compiled at load-time)

```yaml
id: block_large_auto_english
enabled: true
policy_type: english
english: >
  If approved amount is greater than 5000 and approval mode is auto,
  auto approval is not allowed.
hints:
  action:
    type: block
    message: Auto approval is not allowed above 5000.
```

### 3) Agent + tool guardrail

```yaml
id: agent_allowlist_for_approve
enabled: true
policy_type: structured
trigger:
  event: before_tool_call
  tool_id: approve_loan
conditions:
  field: agent_id
  operator: "!="
  value: loan-agent
action:
  type: block
  message: Only loan-agent may approve loans.
```

### 4) Workflow policy using session metadata

```yaml
id: require_human_review_for_large_manual
enabled: true
policy_type: structured
trigger:
  event: before_tool_call
  tool_id: approve_loan
conditions:
  all:
    - field: tool_args.approved_amount
      operator: ">"
      value: 5000
    - field: metadata.human_reviewed
      operator: "!="
      value: true
action:
  type: block
  message: Human review required before large approval.
```

### 5) Final response safety policy

```yaml
id: block_guaranteed_claims
enabled: true
policy_type: structured
trigger:
  event: before_final_response
conditions:
  field: final_response
  operator: contains
  value: guaranteed approval
action:
  type: block
  message: Do not promise guaranteed approval.
```

## CLI

All commands use the `openagentpolicy` entrypoint (stdlib `argparse`, no extra CLI dependency).

### 1) Validate config

```bash
openagentpolicy validate-config openagentpolicy.yaml
```

### 2) Validate inventory

```bash
openagentpolicy validate-inventory inventory.yaml
```

### 3) Validate policy

```bash
openagentpolicy validate-policy policies/auto_approval_structured.yaml --inventory inventory.yaml
```

### 4) Compile policy

```bash
openagentpolicy compile-policy policies/english.yaml --inventory inventory.yaml
openagentpolicy compile-policy policies/ --inventory inventory.yaml
```

### 5) Test policy against an event

Exit code `0` means allow. Exit code `1` means block or restrictive decision.

```bash
openagentpolicy test-policy policies/auto_approval_structured.yaml \
  --event events/high_value_loan.json \
  --inventory inventory.yaml
```

Event file format:

```json
{
  "event_type": "before_tool_call",
  "tool_id": "approve_loan",
  "tool_args": {
    "approved_amount": 50000,
    "approval_mode": "auto"
  },
  "agent_id": "loan-agent",
  "metadata": {
    "human_reviewed": false
  }
}
```

### 6) Generate inventory from traces

```bash
openagentpolicy generate-inventory \
  --traces ./openagentpolicy_traces/events.jsonl \
  --output generated_inventory.yaml
```

### Legacy: full engine check

```bash
openagentpolicy check --config openagentpolicy.yaml --tool approve_loan \
  --args '{"approved_amount": 5000, "approval_mode": "auto"}'
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

Apache-2.0
