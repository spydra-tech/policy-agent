from __future__ import annotations

import json
from pathlib import Path

from openagentpolicy.privacy import PrivacyRedactor
from openagentpolicy.runtime.events import PolicyEvent


class AuditLogger:
    def __init__(
        self,
        log_path: str | None = None,
        *,
        redactor: PrivacyRedactor | None = None,
    ) -> None:
        self.log_path = Path(log_path) if log_path else None
        self._memory: list[PolicyEvent] = []
        self._redactor = redactor

    def log(self, event: PolicyEvent) -> None:
        to_log = self._redactor.redact_event(event) if self._redactor else event
        self._memory.append(to_log)
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(to_log.model_dump_json() + "\n")

    def events(self) -> list[PolicyEvent]:
        return list(self._memory)
