from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openagentpolicy.inventory.schema import Inventory
from openagentpolicy.runtime.events import PolicyEvent

REDACTED_VALUE = "***REDACTED***"


@dataclass
class PrivacyRedactor:
    inventory: Inventory
    redact_keys: tuple[str, ...]

    @classmethod
    def from_config(cls, inventory: Inventory, redact_keys: list[str]) -> "PrivacyRedactor":
        normalized = tuple(k.lower() for k in redact_keys if k)
        return cls(inventory=inventory, redact_keys=normalized)

    def redact_event(self, event: PolicyEvent) -> PolicyEvent:
        sensitive_args = self._sensitive_args_for_tool(event.tool_id)
        return event.model_copy(
            update={
                "tool_args": self.redact_dict(event.tool_args, sensitive_keys=sensitive_args),
                "tool_result": (
                    self.redact_dict(event.tool_result or {})
                    if event.tool_result is not None
                    else None
                ),
                "metadata": self.redact_dict(event.metadata),
            }
        )

    def redact_dict(
        self,
        data: dict[str, Any],
        *,
        sensitive_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        keys = {k.lower() for k in (sensitive_keys or set())}
        return {
            key: self.redact_value(key, value, sensitive_keys=keys)
            for key, value in data.items()
        }

    def redact_value(
        self,
        key: str,
        value: Any,
        *,
        sensitive_keys: set[str] | None = None,
    ) -> Any:
        sensitive_keys = sensitive_keys or set()
        if key.lower() in sensitive_keys or self._is_sensitive_key(key):
            return REDACTED_VALUE
        if isinstance(value, dict):
            return self.redact_dict(value, sensitive_keys=sensitive_keys)
        if isinstance(value, list):
            return [
                self.redact_value(key, item, sensitive_keys=sensitive_keys)
                for item in value
            ]
        return value

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
