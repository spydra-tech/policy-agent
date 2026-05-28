from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openagentpolicy.inventory.schema import Inventory
from openagentpolicy.pii import PiiDetector, redact_spans
from openagentpolicy.runtime.events import PolicyEvent

REDACTED_VALUE = "***REDACTED***"


@dataclass
class PrivacyRedactor:
    inventory: Inventory
    redact_keys: tuple[str, ...]
    pii_detector: PiiDetector | None = None
    scan_fields: tuple[str, ...] = ()

    @classmethod
    def from_config(
        cls,
        inventory: Inventory,
        redact_keys: list[str],
        *,
        pii_detector: PiiDetector | None = None,
        scan_fields: list[str] | None = None,
    ) -> "PrivacyRedactor":
        normalized = tuple(k.lower() for k in redact_keys if k)
        return cls(
            inventory=inventory,
            redact_keys=normalized,
            pii_detector=pii_detector,
            scan_fields=tuple(scan_fields or ()),
        )

    def redact_event(self, event: PolicyEvent) -> PolicyEvent:
        sensitive_args = self._sensitive_args_for_tool(event.tool_id)
        return event.model_copy(
            update={
                "tool_args": self.redact_dict(
                    event.tool_args,
                    sensitive_keys=sensitive_args,
                    scan_strings=self._scan("tool_args"),
                ),
                "tool_result": (
                    self.redact_dict(
                        event.tool_result or {},
                        scan_strings=self._scan("tool_result"),
                    )
                    if event.tool_result is not None
                    else None
                ),
                "metadata": self.redact_dict(
                    event.metadata, scan_strings=self._scan("metadata")
                ),
                "final_response": (
                    self._scan_text(event.final_response)
                    if self._scan("final_response")
                    else event.final_response
                ),
            }
        )

    def redact_dict(
        self,
        data: dict[str, Any],
        *,
        sensitive_keys: set[str] | None = None,
        scan_strings: bool = True,
    ) -> dict[str, Any]:
        keys = {k.lower() for k in (sensitive_keys or set())}
        return {
            key: self.redact_value(
                key, value, sensitive_keys=keys, scan_strings=scan_strings
            )
            for key, value in data.items()
        }

    def redact_value(
        self,
        key: str,
        value: Any,
        *,
        sensitive_keys: set[str] | None = None,
        scan_strings: bool = True,
    ) -> Any:
        sensitive_keys = sensitive_keys or set()
        if key.lower() in sensitive_keys or self._is_sensitive_key(key):
            return REDACTED_VALUE
        if isinstance(value, dict):
            return self.redact_dict(
                value, sensitive_keys=sensitive_keys, scan_strings=scan_strings
            )
        if isinstance(value, list):
            return [
                self.redact_value(
                    key, item, sensitive_keys=sensitive_keys, scan_strings=scan_strings
                )
                for item in value
            ]
        if scan_strings and isinstance(value, str):
            return self._scan_text(value)
        return value

    def redact_result(self, value: Any) -> Any:
        """Redact an arbitrary tool return value.

        Applies key/schema redaction and (when configured) PII value scanning.
        Used for after_tool_call REDACT_RESULT decisions. Note this redacts the
        value returned to the caller; it cannot undo the tool's side effects.
        """
        if isinstance(value, dict):
            return self.redact_dict(value, scan_strings=True)
        if isinstance(value, list):
            return [self.redact_result(item) for item in value]
        if isinstance(value, str):
            return self._scan_text(value)
        return value

    def _scan_text(self, value: str | None) -> str | None:
        if value is None or self.pii_detector is None:
            return value
        spans = self.pii_detector.detect(value)
        return redact_spans(value, spans)

    def _scan(self, field_name: str) -> bool:
        return self.pii_detector is not None and field_name in self.scan_fields

    def _is_sensitive_key(self, key: str) -> bool:
        lowered = key.lower()
        return any(part in lowered for part in self.redact_keys)

    def _sensitive_args_for_tool(self, tool_id: str | None) -> set[str]:
        if not tool_id:
            return set()
        tool = self.inventory.get_tool(tool_id)
        if tool is None:
            return set()
        return {
            arg_name.lower()
            for arg_name, arg_schema in tool.arguments.items()
            if getattr(arg_schema, "sensitive", False)
        }
