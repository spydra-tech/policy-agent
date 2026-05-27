from __future__ import annotations

import json
from pathlib import Path

from openagentpolicy.runtime.events import PolicyEvent


class AuditLogger:
    def __init__(self, log_path: str | None = None) -> None:
        self.log_path = Path(log_path) if log_path else None
        self._memory: list[PolicyEvent] = []

    def log(self, event: PolicyEvent) -> None:
        self._memory.append(event)
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(event.model_dump_json() + "\n")

    def events(self) -> list[PolicyEvent]:
        return list(self._memory)
