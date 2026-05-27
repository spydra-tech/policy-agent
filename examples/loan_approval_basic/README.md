# Loan Approval Basic Example

A complete [openagentpolicy](https://github.com/) demo: annotate Python tools, enforce policies at runtime, record traces, and generate inventory from observed tool calls.

## Install

From the repository root:

```bash
pip install -e ".[dev]"
```

## Project layout

```
loan_approval_basic/
├── app.py                          # Runnable demo
├── openagentpolicy.yaml              # Engine config (inventory, policies, traces)
├── inventory.yaml                    # Tool definitions
├── policies/
│   ├── auto_approval_structured.yaml # Structured policy (enabled)
│   └── auto_approval_english.yaml    # English policy (disabled by default)
├── events/
│   └── high_value_loan.json          # Sample event for CLI test-policy
└── openagentpolicy_traces/           # Created when you run app.py (traces enabled)
    └── events.jsonl
```

## Run the app

```bash
cd examples/loan_approval_basic
python app.py
```

Expected output:

1. **Small auto loan** (`approved_amount=4000`, `approval_mode=auto`) → **ALLOWED**
2. **Large auto loan** (`approved_amount=7500`, `approval_mode=auto`) → **BLOCKED**

The app uses `@policy_tool` so enforcement runs automatically before and after each tool call. Traces are written to `./openagentpolicy_traces/events.jsonl`.

## Policy: blocked example

Structured policy (`policies/auto_approval_structured.yaml`):

- **Trigger:** `before_tool_call` on `approve_loan`
- **When:** `approved_amount > 5000` **and** `approval_mode == auto`
- **Action:** `block`

Validate and test without running the app:

```bash
# Validate policy against inventory
openagentpolicy validate-policy policies/auto_approval_structured.yaml \
  --inventory inventory.yaml

# Simulate the blocked case
openagentpolicy test-policy policies/auto_approval_structured.yaml \
  --event events/high_value_loan.json \
  --inventory inventory.yaml
```

`test-policy` exits with code `1` when the decision is `block`.

## Compile English policy

English policies are compiled to structured form using inventory field names and aliases.

1. Enable the English policy in `policies/auto_approval_english.yaml`:

   ```yaml
   enabled: true
   ```

2. Optionally disable the structured policy (`enabled: false` on `auto_approval_structured.yaml`) to avoid duplicate rules.

3. Compile and inspect:

```bash
openagentpolicy compile-policy policies/auto_approval_english.yaml \
  --inventory inventory.yaml
```

Example English text:

```yaml
english: >
  If approved amount is greater than 5000, auto approval is not allowed.
```

The compiler resolves `approved amount` → `tool_args.approved_amount` and `auto approval` → `tool_args.approval_mode == auto`, then emits an enforceable structured policy.

Validate:

```bash
openagentpolicy validate-policy policies/auto_approval_english.yaml \
  --inventory inventory.yaml
```

## Generate trace-derived inventory

After running `app.py`, traces are stored as JSONL. Generate a suggested inventory from observed tool usage:

```bash
openagentpolicy generate-inventory \
  --traces ./openagentpolicy_traces/events.jsonl \
  --output ./generated_inventory.yaml
```

The generated file includes:

- Tools observed (`approve_loan`, etc.)
- Argument names and inferred types
- Min/max for numbers, observed values for low-cardinality strings
- Result fields and presence rates

Use this as a starting point when bootstrapping `inventory.yaml` from production or staging traffic.

## Other CLI commands

```bash
openagentpolicy validate-config openagentpolicy.yaml
openagentpolicy validate-inventory inventory.yaml
```

## How it works in code

```python
from openagentpolicy import configure, policy_tool

configure("openagentpolicy.yaml")

@policy_tool(id="approve_loan", risk_level="high", side_effect=True)
def approve_loan(application_id: str, approved_amount: float, approval_mode: str):
    return {"status": "approved", ...}
```

`configure()` loads config, inventory, and policies. Each call to `approve_loan`:

1. Builds a `before_tool_call` event and evaluates policies
2. Blocks with `PolicyViolation` if a rule matches
3. Runs the function on success
4. Builds an `after_tool_call` event and evaluates again
5. Appends redacted trace lines to `openagentpolicy_traces/events.jsonl`
