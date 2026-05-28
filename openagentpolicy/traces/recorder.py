from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from openagentpolicy.config import TracesConfig, resolve_config_path
from openagentpolicy.privacy import PrivacyRedactor
from openagentpolicy.runtime.decisions import PolicyDecision

REDACTED_VALUE = "***REDACTED***"


class ToolCallTrace(BaseModel):
    """In-memory trace entry for inventory discovery."""

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallTraceCollector:
    """Collect tool calls in memory for inventory discovery from traces."""

    def __init__(self) -> None:
        self._traces: list[ToolCallTrace] = []

    def record(self, tool_name: str, arguments: dict[str, Any] | None = None) -> None:
        self._traces.append(
            ToolCallTrace(tool_name=tool_name, arguments=arguments or {})
        )

    def get_traces(self) -> list[ToolCallTrace]:
        return list(self._traces)

    def clear(self) -> None:
        self._traces.clear()


class TraceEventRecord(BaseModel):
    event_type: str
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    tool_id: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    tool_result: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None


class TraceRecorder:
    """Base trace recorder; no-op when disabled."""

    enabled: bool = False

    def record_event(
        self,
        *,
        event_type: str,
        tool_id: str,
        tool_args: dict[str, Any] | None = None,
        tool_result: dict[str, Any] | None = None,
        decision: PolicyDecision | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        return None


class LocalTraceRecorder(TraceRecorder):
    """Append tool-call trace events to a local JSONL file."""

    def __init__(
        self,
        events_path: Path,
        *,
        redactor: PrivacyRedactor | None = None,
    ) -> None:
        self.enabled = True
        self.events_path = events_path.resolve()
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self._redactor = redactor

    def record_event(
        self,
        *,
        event_type: str,
        tool_id: str,
        tool_args: dict[str, Any] | None = None,
        tool_result: dict[str, Any] | None = None,
        decision: PolicyDecision | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        record = TraceEventRecord(
            event_type=event_type,
            timestamp=timestamp or datetime.now(timezone.utc),
            tool_id=tool_id,
            tool_args=self._redact_dict(tool_args or {}, tool_id=tool_id),
            tool_result=(
                self._redact_dict(tool_result, tool_id=tool_id)
                if tool_result is not None
                else None
            ),
            decision=_decision_to_dict(decision),
        )
        line = json.dumps(record.model_dump(mode="json"), default=str)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def read_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events

    def clear(self) -> None:
        if self.events_path.exists():
            self.events_path.unlink()

    def _redact_dict(
        self, data: dict[str, Any], *, tool_id: str | None
    ) -> dict[str, Any]:
        if self._redactor is None:
            return redact_sensitive_dict(data)
        sensitive_args = self._redactor._sensitive_args_for_tool(tool_id)
        return self._redactor.redact_dict(data, sensitive_keys=sensitive_args)


class InMemoryTraceRecorder(TraceRecorder):
    """In-memory trace recorder for tests."""

    def __init__(self, *, redactor: PrivacyRedactor | None = None) -> None:
        self.enabled = True
        self.events: list[TraceEventRecord] = []
        self._redactor = redactor

    def record_event(
        self,
        *,
        event_type: str,
        tool_id: str,
        tool_args: dict[str, Any] | None = None,
        tool_result: dict[str, Any] | None = None,
        decision: PolicyDecision | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        self.events.append(
            TraceEventRecord(
                event_type=event_type,
                timestamp=timestamp or datetime.now(timezone.utc),
                tool_id=tool_id,
                tool_args=self._redact_dict(tool_args or {}, tool_id=tool_id),
                tool_result=(
                    self._redact_dict(tool_result, tool_id=tool_id)
                    if tool_result is not None
                    else None
                ),
                decision=_decision_to_dict(decision),
            )
        )

    def _redact_dict(
        self, data: dict[str, Any], *, tool_id: str | None
    ) -> dict[str, Any]:
        if self._redactor is None:
            return redact_sensitive_dict(data)
        sensitive_args = self._redactor._sensitive_args_for_tool(tool_id)
        return self._redactor.redact_dict(data, sensitive_keys=sensitive_args)


def create_trace_recorder(
    config: TracesConfig,
    base_path: Path,
    *,
    redactor: PrivacyRedactor | None = None,
) -> TraceRecorder | None:
    if not config.enabled:
        return None
    provider = config.store.provider
    if provider == "local":
        directory = resolve_config_path(base_path, config.store.path)
        return LocalTraceRecorder(directory / "events.jsonl", redactor=redactor)
    raise ValueError(f"Unknown trace store provider: {provider}")


def redact_sensitive_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {key: redact_sensitive_value(key, value) for key, value in data.items()}


def redact_sensitive_value(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        return REDACTED_VALUE
    if isinstance(value, dict):
        return redact_sensitive_dict(value)
    if isinstance(value, list):
        return [redact_sensitive_value(key, item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(
        part in lowered
        for part in ("password", "token", "secret", "pan", "aadhaar", "ssn")
    )


def _decision_to_dict(decision: PolicyDecision | None) -> dict[str, Any] | None:
    if decision is None:
        return None
    return decision.model_dump(mode="json")
