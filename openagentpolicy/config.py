from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from openagentpolicy.runtime.decisions import DecisionType


class ApplicationConfig(BaseModel):
    id: str
    name: str | None = None
    environment: str | None = None


class RuntimeConfig(BaseModel):
    default_agent_id: str | None = None


class InventoryConfig(BaseModel):
    provider: str = "file"
    path: str | None = None
    url: str | None = None
    conflict_strategy: str = "merge_with_warning"


class PoliciesConfig(BaseModel):
    provider: str = "directory"
    path: str | None = None
    paths: list[str] = Field(default_factory=list)
    url: str | None = None
    support_english: bool = True
    compile_on_startup: bool = True
    require_compiled: bool = False
    english_compiler: str = "rule_based"
    ai: dict[str, Any] = Field(default_factory=dict)


class CompilerConfig(BaseModel):
    enabled: bool = True


class OnPolicyError(str, Enum):
    ALLOW_WITH_WARNING = "allow_with_warning"
    BLOCK = "block"
    RAISE = "raise"


class EnforcementConfig(BaseModel):
    default_action: DecisionType = DecisionType.ALLOW
    on_policy_error: OnPolicyError = OnPolicyError.ALLOW_WITH_WARNING
    audit_enabled: bool = True
    fail_on_unresolved_fields: bool = False
    fail_on_unenforceable: bool = False


class TraceStoreConfig(BaseModel):
    provider: str = "local"
    path: str = "./openagentpolicy_traces"


class TracesConfig(BaseModel):
    enabled: bool = False
    store: TraceStoreConfig = Field(default_factory=TraceStoreConfig)


class PrivacyConfig(BaseModel):
    redact_keys: list[str] = Field(
        default_factory=lambda: [
            "password",
            "token",
            "secret",
            "pan",
            "aadhaar",
            "ssn",
        ]
    )


class EngineConfig(BaseModel):
    application: ApplicationConfig | None = None
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    inventory: InventoryConfig = Field(default_factory=InventoryConfig)
    compiler: CompilerConfig = Field(default_factory=CompilerConfig)
    policies: PoliciesConfig = Field(default_factory=PoliciesConfig)
    enforcement: EnforcementConfig = Field(default_factory=EnforcementConfig)
    traces: TracesConfig = Field(default_factory=TracesConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    audit_log: str | None = None

    @model_validator(mode="before")
    @classmethod
    def merge_legacy_audit(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("audit_log") and "enforcement" not in data:
            data = dict(data)
            data.setdefault("enforcement", {})["audit_enabled"] = True
        return data


def resolve_config_path(base_path: Path, path: str) -> Path:
    """Resolve a config path relative to the config file directory."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = base_path / candidate
    return candidate.resolve()


def load_config(path: str | Path) -> EngineConfig:
    config_path = Path(path).resolve()
    text = config_path.read_text(encoding="utf-8")
    if config_path.suffix in {".yaml", ".yml"}:
        data: dict[str, Any] = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    return EngineConfig.model_validate(data)


def config_base_path(path: str | Path) -> Path:
    return Path(path).resolve().parent
