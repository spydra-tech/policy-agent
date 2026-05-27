# openagentpolicy

Policy enforcement runtime for AI and agentic applications. Annotate Python functions with `@policy_tool`, load inventory and policies from YAML or remote services, and enforce structured rules at runtime.

## Quickstart

```bash
pip install -e ".[dev]"
```

```python
from openagentpolicy import configure, policy_tool

configure("openagentpolicy.yaml")

@policy_tool
def approve_loan(application_id: str, approved_amount: float):
    return {"status": "approved"}
```

See [examples/loan_approval_basic](examples/loan_approval_basic/) for a minimal tool-only sample, and [examples/agentic_loan_desk](examples/agentic_loan_desk/) for an agentic walkthrough with English compilation, tool-level and agent-level policies, and scripted enforcement scenarios.

## Configuration

```yaml
application:
  id: my_app
  environment: production

inventory:
  provider: file
  path: ./inventory.yaml

policies:
  provider: directory
  path: ./policies
  compile_on_startup: true

traces:
  enabled: true
  store:
    provider: local
    path: ./openagentpolicy_traces

enforcement:
  default_action: allow
  audit_enabled: true
```

## CLI

All commands use the `openagentpolicy` entrypoint (stdlib `argparse`, no extra CLI dependencies).

### 1. Validate config

Check that `openagentpolicy.yaml` parses and matches the engine schema.

```bash
openagentpolicy validate-config openagentpolicy.yaml
```

Example:

```bash
openagentpolicy validate-config examples/loan_approval_basic/openagentpolicy.yaml
```

### 2. Validate inventory

Check that `inventory.yaml` is valid and lists tools with unique ids.

```bash
openagentpolicy validate-inventory inventory.yaml
```

Example:

```bash
openagentpolicy validate-inventory examples/loan_approval_basic/inventory.yaml
```

### 3. Validate policy

Validate a policy file (or directory) against an inventory: structured schema, known `tool_id`, resolvable condition fields, and compilable English policies.

```bash
openagentpolicy validate-policy policies/auto_approval_structured.yaml --inventory inventory.yaml
```

Example:

```bash
openagentpolicy validate-policy \
  examples/loan_approval_basic/policies/auto_approval_structured.yaml \
  --inventory examples/loan_approval_basic/inventory.yaml
```

### 4. Compile policy

Compile English or structured policies into enforceable structured form (prints YAML compile results).

```bash
openagentpolicy compile-policy policies/english.yaml --inventory inventory.yaml
```

For a directory:

```bash
openagentpolicy compile-policy policies/ --inventory inventory.yaml
```

### 5. Test policy

Evaluate a policy against a sample event file. Exit code `0` = allow, `1` = block or other restrictive decision.

```bash
openagentpolicy test-policy policies/auto_approval_structured.yaml \
  --event events/high_value_loan.json \
  --inventory inventory.yaml
```

Example (expects block):

```bash
openagentpolicy test-policy \
  examples/loan_approval_basic/policies/auto_approval_structured.yaml \
  --event examples/loan_approval_basic/events/high_value_loan.json \
  --inventory examples/loan_approval_basic/inventory.yaml
```

Event file format:

```json
{
  "event_type": "before_tool_call",
  "tool_id": "approve_loan",
  "tool_args": {
    "amount": 50000,
    "risk_score": 0.85
  }
}
```

### 6. Generate inventory from traces

Build `generated_inventory.yaml` from JSONL trace events recorded by `@policy_tool`.

```bash
openagentpolicy generate-inventory \
  --traces ./openagentpolicy_traces/events.jsonl \
  --output generated_inventory.yaml
```

### Legacy: full engine check

Run enforcement using the full config file (inventory + policies from config):

```bash
openagentpolicy check --config openagentpolicy.yaml --tool approve_loan \
  --args '{"amount": 5000, "risk_score": 0.2}'
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

Apache-2.0
# openagentpolicy
