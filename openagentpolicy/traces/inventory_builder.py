from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from openagentpolicy.inventory.schema import ArgumentSchema, Inventory, Tool
from openagentpolicy.traces.recorder import REDACTED_VALUE, ToolCallTraceCollector

LOW_CARDINALITY_THRESHOLD = 20
POLICY_USABLE_MIN_PRESENCE = 0.05


class GeneratedFromMeta(BaseModel):
    source: str = "traces"
    trace_count: int = 0


class ObservedArgument(BaseModel):
    type: str
    observed_values: list[Any] | None = None
    observed_min: float | None = None
    observed_max: float | None = None
    presence_rate: float = 0.0
    policy_usable: bool = True


class ObservedTool(BaseModel):
    id: str
    observed_arguments: dict[str, ObservedArgument] = Field(default_factory=dict)
    observed_result_fields: dict[str, ObservedArgument] = Field(
        default_factory=dict
    )
    common_predecessors: list[str] = Field(default_factory=list)
    common_successors: list[str] = Field(default_factory=list)


class GeneratedInventory(BaseModel):
    generated_from: GeneratedFromMeta
    tools: list[ObservedTool] = Field(default_factory=list)


class TraceInventoryBuilder:
    """Build inventory from JSONL trace events or in-memory collectors."""

    def build_from_jsonl(self, traces_path: str | Path) -> GeneratedInventory:
        events = load_trace_events(traces_path)
        return self.build_from_events(events)

    def build_from_events(self, events: list[dict[str, Any]]) -> GeneratedInventory:
        invocations = _pair_invocations(events)
        trace_count = _count_traces(invocations, events)
        tools = _infer_tools(invocations)
        _apply_sequences(tools, invocations)
        return GeneratedInventory(
            generated_from=GeneratedFromMeta(source="traces", trace_count=trace_count),
            tools=sorted(tools, key=lambda tool: tool.id),
        )

    def write_yaml(
        self, inventory: GeneratedInventory, output_path: str | Path
    ) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = inventory.model_dump(exclude_none=True)
        path.write_text(
            yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        return path

    def build(self, recorder: ToolCallTraceCollector) -> Inventory:
        """Legacy: build standard inventory from in-memory trace collector."""
        seen: set[str] = set()
        tools: list[Tool] = []
        for trace in recorder.get_traces():
            if trace.tool_name in seen:
                continue
            seen.add(trace.tool_name)
            tools.append(
                Tool(
                    id=trace.tool_name,
                    name=trace.tool_name,
                    description="Discovered from trace",
                    arguments={
                        key: ArgumentSchema(type="string")
                        for key in trace.arguments
                    },
                )
            )
        return Inventory(tools=tools)


def load_trace_events(traces_path: str | Path) -> list[dict[str, Any]]:
    path = Path(traces_path)
    if not path.exists():
        raise FileNotFoundError(f"Trace file not found: {path}")
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _pair_invocations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending: dict[str, dict[str, Any]] = {}
    invocations: list[dict[str, Any]] = []

    for event in events:
        event_type = event.get("event_type")
        tool_id = event.get("tool_id")
        if not tool_id:
            continue

        if event_type == "before_tool_call":
            pending[tool_id] = event
            continue

        if event_type == "after_tool_call" and tool_id in pending:
            before = pending.pop(tool_id)
            invocations.append(
                {
                    "tool_id": tool_id,
                    "tool_args": before.get("tool_args") or {},
                    "tool_result": event.get("tool_result"),
                    "trace_id": event.get("trace_id")
                    or before.get("trace_id"),
                    "timestamp": event.get("timestamp"),
                }
            )

    for tool_id, before in pending.items():
        invocations.append(
            {
                "tool_id": tool_id,
                "tool_args": before.get("tool_args") or {},
                "tool_result": None,
                "trace_id": before.get("trace_id"),
                "timestamp": before.get("timestamp"),
            }
        )

    return invocations


def _count_traces(
    invocations: list[dict[str, Any]], events: list[dict[str, Any]]
) -> int:
    trace_ids = {
        inv["trace_id"] for inv in invocations if inv.get("trace_id") is not None
    }
    if trace_ids:
        return len(trace_ids)
    return max(len(invocations), len(events))


def _infer_tools(invocations: list[dict[str, Any]]) -> list[ObservedTool]:
    by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for invocation in invocations:
        by_tool[invocation["tool_id"]].append(invocation)

    tools: list[ObservedTool] = []
    for tool_id, tool_invocations in by_tool.items():
        tools.append(
            ObservedTool(
                id=tool_id,
                observed_arguments=_infer_argument_stats(
                    [inv["tool_args"] for inv in tool_invocations]
                ),
                observed_result_fields=_infer_argument_stats(
                    [
                        inv["tool_result"]
                        for inv in tool_invocations
                        if inv.get("tool_result")
                    ],
                    allow_empty=True,
                ),
            )
        )
    return tools


def _infer_argument_stats(
    payloads: list[dict[str, Any]], *, allow_empty: bool = False
) -> dict[str, ObservedArgument]:
    if not payloads:
        return {}

    all_keys: set[str] = set()
    for payload in payloads:
        all_keys.update(payload.keys())

    total = len(payloads)
    observed: dict[str, ObservedArgument] = {}
    for key in sorted(all_keys):
        values = [payload.get(key) for payload in payloads if key in payload]
        present_count = len(values)
        presence_rate = present_count / total if total else 0.0
        non_null_values = [v for v in values if v is not None]
        arg_type = _infer_dominant_type(non_null_values)
        stats = ObservedArgument(
            type=arg_type,
            presence_rate=round(presence_rate, 4),
            policy_usable=_is_policy_usable(non_null_values, presence_rate),
        )

        if arg_type == "string":
            unique = _unique_non_redacted_strings(non_null_values)
            if 0 < len(unique) <= LOW_CARDINALITY_THRESHOLD:
                stats.observed_values = sorted(unique, key=lambda v: str(v))
        elif arg_type == "number":
            numbers = [float(v) for v in non_null_values if _is_number(v)]
            if numbers:
                stats.observed_min = min(numbers)
                stats.observed_max = max(numbers)

        if stats.policy_usable or not allow_empty:
            observed[key] = stats

    return observed


def _apply_sequences(
    tools: list[ObservedTool], invocations: list[dict[str, Any]]
) -> None:
    sequences: dict[str, list[str]] = defaultdict(list)

    by_trace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for invocation in invocations:
        trace_id = invocation.get("trace_id")
        if trace_id:
            by_trace[str(trace_id)].append(invocation)

    if by_trace:
        for trace_invocations in by_trace.values():
            ordered = sorted(
                trace_invocations,
                key=lambda inv: str(inv.get("timestamp") or ""),
            )
            sequences[str(id(trace_invocations))] = [
                inv["tool_id"] for inv in ordered
            ]
    else:
        sequences["default"] = [inv["tool_id"] for inv in invocations]

    predecessor_counts: dict[str, Counter[str]] = defaultdict(Counter)
    successor_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for sequence in sequences.values():
        for index, tool_id in enumerate(sequence):
            if index > 0:
                predecessor_counts[tool_id][sequence[index - 1]] += 1
            if index < len(sequence) - 1:
                successor_counts[tool_id][sequence[index + 1]] += 1

    tool_map = {tool.id: tool for tool in tools}
    for tool_id, tool in tool_map.items():
        if predecessor_counts[tool_id]:
            tool.common_predecessors = [
                name
                for name, _ in predecessor_counts[tool_id].most_common(5)
            ]
        if successor_counts[tool_id]:
            tool.common_successors = [
                name for name, _ in successor_counts[tool_id].most_common(5)
            ]


def _infer_dominant_type(values: list[Any]) -> str:
    if not values:
        return "null"
    type_counts = Counter(_value_type(value) for value in values)
    return type_counts.most_common(1)[0][0]


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _unique_non_redacted_strings(values: list[Any]) -> list[str]:
    unique: set[str] = set()
    for value in values:
        if isinstance(value, str) and value != REDACTED_VALUE:
            unique.add(value)
    return list(unique)


def _is_policy_usable(values: list[Any], presence_rate: float) -> bool:
    if presence_rate < POLICY_USABLE_MIN_PRESENCE:
        return False
    if not values:
        return False
    if all(value == REDACTED_VALUE for value in values):
        return False
    return True
