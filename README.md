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
- Tool guardrails enforce constraints at `before_tool_call` (can prevent the call) and observe results at `after_tool_call` (cannot prevent side effects). See [Event semantics](#event-semantics-before-vs-after-tool-call).
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

## Event semantics: before vs after tool call

Tool enforcement runs at two points, and they have **different capabilities**:

| Event | Runs | Can prevent side effects? | Allowed actions |
| --- | --- | --- | --- |
| `before_tool_call` | before the tool executes | **Yes** | `block`, `modify_args`, `warn`, `log_only`, `allow` |
| `after_tool_call` | after the tool has returned | **No** | `redact_result`, `warn`, `log_only`, `escalate` |

Important: by the time `after_tool_call` runs, the tool has **already executed**
and any side effects (writes, payments, emails) have **already happened**. An
`after_tool_call` policy therefore cannot block, modify args, or redirect the
call — those decisions are ignored (with a warning in logs).

What `after_tool_call` *can* do:

- `redact_result` — actually redacts the value returned to the caller using the
  configured [privacy redactor](#privacy-and-pii-redaction) (key/schema rules +
  optional PII scanning). This sanitizes what flows downstream, but does not
  undo the side effect.
- `warn` / `log_only` — record the condition.
- `escalate` — emit an escalation signal for out-of-band review.

If you need to *prevent* an action (the Example A failure mode — "don't approve
above 5000 in auto mode"), the policy must trigger on `before_tool_call`. Put
side-effecting work behind a `before_tool_call` guard; use `after_tool_call`
only to sanitize or flag results you cannot stop.

## Authoring vs Runtime Modes

`openagentpolicy` now separates policy authoring from runtime enforcement.

- **Authoring / compilation mode**
  - Input can be English policy text.
  - Compiler resolves terms against inventory.
  - Compiler returns either:
    - compiled structured/compiled policy object, or
    - clear `not_enforceable` / `needs_review` result with errors.
  - Only compiled structured policy should be saved/activated.

- **Runtime enforcement mode**
  - Runtime enforces deterministic structured/compiled policies only.
  - English is an authoring format, not runtime enforcement format.
  - In production, recommended config:
    - `compiler.enabled: false`
    - `policies.require_compiled: true`
    - `enforcement.fail_on_unresolved_fields: true`
    - `enforcement.fail_on_unenforceable: true`

### Correct production flow

English policy from UI/API
-> compile against inventory
-> validate enforceability
-> generate deterministic compiled policy
-> review/approve
-> save compiled policy
-> runtime enforces compiled policy only

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

## Scope and Limitations

Read these before relying on `openagentpolicy` as a control. They are deliberate
design boundaries, not bugs.

### Enforcement is in-process, at the boundaries you wrap

Policies only fire when a tool is invoked **through the decorated function in the
same process**. The "framework-agnostic" claim holds at those boundaries and no
further:

- If a framework, planner, or scheduler invokes the *underlying* callable
  directly (bypassing the `@policy_tool` wrapper), it is invisible to enforcement.
- Remote/out-of-band tools (HTTP services, MCP servers, other processes) are not
  intercepted unless the call into them is itself wrapped.
- The output guard only sees text you explicitly pass to
  `check_final_response(...)` / `check_final_response_any(...)`.

Treat the decorated callable and the explicit output check as the trust boundary.
Anything reaching a tool by another path is unenforced.

### `before_final_response` is a string check, not semantic filtering

Final-response policies match on the response text using `contains` (case-
insensitive by default) and `regex` operators. This is literal string matching:

- It catches `"guaranteed approval"` but **not** `"approval is guaranteed"`,
  `"we guarantee you'll be approved"`, or other paraphrases.
- It is not a semantic classifier and does not understand intent or meaning.

Use it for known forbidden phrases and patterns. Do not mistake it for an
output-safety/LLM-judge layer; pair it with one if you need semantic coverage.

### Default posture is "permit unless explicitly blocked"

With `default_action: allow` (the default) plus fail-open field resolution, the
system's safety stance is **allow by default, block only on an explicit match**.
A policy that never matches (or whose tool is never wrapped) results in the
action being permitted.

For regulated deployments (BFSI, healthcare), this default is a deliberate
decision to revisit. Many such buyers will want **`default_action: block`** as
the baseline — at minimum for `side_effect: true`, high-risk tools — so that the
posture becomes "deny unless explicitly allowed." Load-time validation already
hard-fails on unresolved fields when `default_action: allow` (see
[Unresolved field safety](#unresolved-field-safety-fail-open-protection)), but
that only protects against typos, not against unwrapped or out-of-band calls.

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
  fail_on_unresolved_fields: false  # see note below

privacy:
  redact_keys: [password, token, secret, pan, aadhaar, ssn]
  pii_detection:
    enabled: false          # opt-in; off by default
    engine: regex           # regex | presidio
    languages: [en]
    entities: [CREDIT_CARD, EMAIL_ADDRESS, PHONE_NUMBER, IN_PAN, IN_AADHAAR, US_SSN]
    scan_fields: [final_response, tool_result, tool_args]
```

### Unresolved field safety (fail-open protection)

Every policy condition field is validated against the event context and
inventory at load time. A field that does not resolve (a typo like
`tool_args.amount` instead of `tool_args.approved_amount`, or a field not
available for the trigger event) is handled as follows:

- `fail_on_unresolved_fields: true` — startup fails on any unresolved field.
- `fail_on_unresolved_fields: false` (default):
  - If `default_action: allow` (**fail open**), unresolved condition fields are
    still rejected at startup. A misspelled field would otherwise silently never
    match and allow the guarded action — the worst outcome for a governance
    tool, so this is treated as a hard error.
  - If `default_action: block` (**fail closed**), unresolved fields are logged
    as warnings, because a non-matching policy still blocks.

Action-shape problems (e.g. a `block` action on `after_tool_call`, which the
runtime cannot honor) only fail startup under `fail_on_unresolved_fields: true`,
since they do not fail open.

## Privacy and PII Redaction

Redaction runs in two complementary layers before anything is written to audit
logs or traces:

1. **Key/schema redaction (always on, deterministic).**
   - Any field whose name matches `privacy.redact_keys` is masked.
   - Any tool argument flagged `sensitive: true` in inventory is masked.
   - This layer never inspects values, so it is fast and predictable.

2. **Value-level PII detection (optional, opt-in).**
   - Scans free-text values (e.g. `final_response`, string args/results) for PII
     that is not captured by key names.
   - Controlled by `privacy.pii_detection`.

### Engines

- `engine: regex` (default when enabled): deterministic, local, dependency-free.
  Uses regex plus checksum validation — Luhn for credit cards, Verhoeff for
  Aadhaar — to keep false positives low. Recommended for production because it is
  reproducible and needs no model calls.
- `engine: presidio`: value-level NER + recognizers via Microsoft Presidio. Best
  when you need broad free-text PII (names, addresses, locations). Requires the
  optional dependency:

```bash
pip install openagentpolicy[pii]
```

Presidio is imported lazily, so the core runtime stays dependency-free. Because
its NER recognizers are model-dependent, prefer `regex` when you only need
structured identifiers (PAN, Aadhaar, SSN, cards).

`scan_fields` controls which event fields are scanned for PII values. Key/schema
redaction always applies regardless of `scan_fields`.

### Programmatic use

```python
from openagentpolicy.pii import RegexPiiDetector, redact_spans

detector = RegexPiiDetector.from_entities(["EMAIL_ADDRESS", "IN_PAN"])
text = "Mail john@example.com, PAN ABCDE1234F"
spans = detector.detect(text)
safe = redact_spans(text, spans)
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

## English Policy Compiler Modes (Rule-Based, AI, Hybrid)

English policies can be compiled using three strategies:

- `hybrid` (**default; recommended for free-form authoring**): AI first, then
  deterministic fallback. Use this when authors write policies in natural
  language. If the AI translator is unavailable (no API key/SDK/response), it
  degrades gracefully to the rule-based result — no network dependency is
  required for startup.
- `rule_based` (**locked template grammar**): deterministic matching of a small,
  fixed set of sentence shapes against inventory. It does not attempt to parse
  arbitrary English — anything outside the documented grammar is reported as
  `not_enforceable`/`needs_review` rather than guessed. Choose this when you want
  a fixed, auditable grammar with no model calls.
- `ai`: LLM conversion to structured policy, still schema/inventory validated and
  corroborated by the rule-based compiler before activation.

The rule-based grammar is intentionally small and is **not** meant to grow to
cover natural English. If you find yourself wanting another sentence pattern,
prefer `hybrid` rather than expanding the regex set. The exact supported grammar
is documented below under "Rule-based grammar (locked templates)".

### Config

```yaml
policies:
  provider: directory
  path: ./policies
  support_english: true
  english_compiler: hybrid        # default; one of: hybrid | rule_based | ai
  ai:
    model: gpt-4.1-mini
    api_key_env: OPENAI_API_KEY
    base_url: null                # optional custom endpoint
```

> Note: there is no confidence threshold. A model's self-reported confidence is
> not a calibrated probability, so it is not used as a safety gate. AI output is
> auto-`compiled` only when the deterministic rule-based compiler independently
> produces an equivalent structured policy (see Safety model below).

### Mode behavior

- `rule_based`
  - Uses deterministic parsing from `openagentpolicy/policies/compiler.py`
  - Best for controlled policy templates and strict reproducibility
  - Supports only the fixed grammar documented below; out-of-grammar text is
    not guessed

- `ai`
  - Uses an LLM translator to generate structured policy JSON
  - Validates generated policy with schema + inventory alignment checks
  - Corroborates against the deterministic rule-based compiler
  - Returns:
    - `compiled` when valid, inventory-aligned, AND the deterministic compiler
      independently produces an equivalent structured policy
    - `needs_review` when output is uncorroborated (the deterministic compiler
      disagrees or cannot independently compile the rule), or shape is invalid
    - `not_enforceable` when policy references unknown tools/fields

- `hybrid`
  - Tries AI first
  - If AI does not produce `compiled`, runs the rule-based compiler
  - Uses deterministic output when the fallback succeeds
  - Surfaces a genuine AI candidate (schema-valid, inventory-aligned, but
    uncorroborated) as `needs_review`; if there is no AI signal at all (e.g. the
    translator is unavailable), it defers to the deterministic result instead of
    masking it with a generic review status

### Runtime requirements for AI mode

- Install OpenAI SDK in your environment (`pip install openai`)
- Set API key in env variable configured by `policies.ai.api_key_env` (default `OPENAI_API_KEY`)
- Keep `support_english: true`

If AI is unavailable (no key/dependency/response), AI mode returns `needs_review`; hybrid mode will attempt deterministic fallback automatically.

### Safety model

Even in AI mode, generated policy is never enforced blindly:

1. Parse model output as JSON
2. Validate against `Policy` schema
3. Validate `tool_id` and condition field paths against inventory
4. Require deterministic corroboration: the rule-based compiler must
   independently produce a semantically equivalent structured policy
5. Enforce only `compiled` policies

The trust signal is agreement between an LLM and an independent deterministic
compiler — not a self-reported confidence score. Uncorroborated AI output is
surfaced as `needs_review` for a human to approve, never auto-activated. This
keeps natural-language flexibility while preserving enforcement safety.

### Rule-based grammar (locked templates)

The rule-based compiler recognizes only the following sentence shapes. A leading
`if` is optional for the comparison templates. Terms in `<...>` are resolved
against inventory (argument names, aliases, descriptions, and `allowed_values`);
unresolved terms make the policy `not_enforceable`.

| English template | Compiles to |
| --- | --- |
| `<field> is greater than\|more than\|above <number>` | `field > number` |
| `<field> is less than\|below <number>` | `field < number` |
| `<field> is equal to <number>` | `field == number` |
| `if <field> is missing` | `field not_exists` |
| value phrase from `allowed_values` (e.g. `auto approval`) | `field == "<value>"` |
| `only <agent> may call\|use <tool>` | `agent_id != <agent>` |

Action is taken from the policy's **consequent clause** only:

- block intent — `not allowed`, `not permitted`, `may not`, `must not`,
  `should not`, `cannot`, `can't` → `action: block`
- `warn` → `action: warn`
- otherwise supply an explicit `hints.action`; without one the action is
  undetermined and the policy is `not_enforceable` (it will not silently block).

Anything not matching the above is out of grammar. Do not extend this set to
chase natural English — switch the policy (or the runtime) to `hybrid` instead.
The authoritative definition lives in the module docstring of
`openagentpolicy/policies/compiler.py`.

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

## English Compilation API

Use the UI/backend-facing compile API:

```python
from openagentpolicy.compiler import compile_english_policy

result = compile_english_policy(
    english="If approved amount is greater than 5000, auto approval is not allowed.",
    inventory=inventory,
    policy_id="policy_auto_approval_threshold",
    action_hint={"type": "block", "message": "Auto approval is not allowed above 5000."},
)

if result.status.value == "compiled":
    compiled_policy = result.compiled_policy
    # persist compiled policy
else:
    # show result.errors / result.missing_terms / result.suggested_fixes
    pass
```

Compiled policy shape example:

```yaml
id: policy_auto_approval_threshold
policy_type: compiled
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
source:
  english: If approved amount is greater than 5000, auto approval is not allowed.
  compiler_version: "1.0"
validation:
  enforceability: enforceable
```

Not-enforceable example:

English:
`If KYC is not verified, do not approve the loan.`

If `kyc_status` is not in inventory, compile returns `not_enforceable` with missing terms and actionable fixes.

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

Compile one English policy string to deterministic compiled policy:

```bash
openagentpolicy compile-english \
  --inventory inventory.yaml \
  --policy-id policy_auto_approval_threshold \
  --english "If approved amount is greater than 5000, auto approval is not allowed." \
  --output compiled_policy.yaml
```

Explain one policy against inventory:

```bash
openagentpolicy explain-policy \
  --inventory inventory.yaml \
  --policy policies/policy.yaml
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

### Imperative engine check

Run a single tool-call decision against the configured runtime, without wrapping
any code:

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
