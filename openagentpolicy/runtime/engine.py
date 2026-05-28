from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from openagentpolicy.audit.logger import AuditLogger
from openagentpolicy.config import EngineConfig, OnPolicyError, config_base_path, load_config
from openagentpolicy.inventory.resolver import InventoryResolver
from openagentpolicy.inventory.schema import Inventory
from openagentpolicy.privacy import PrivacyRedactor
from openagentpolicy.policies.providers import PolicyProvider
from openagentpolicy.policies.schema import (
    CompileStatus,
    Policy,
    PolicyCompileResult,
    TriggerEvent,
)
from openagentpolicy.runtime.decisions import DecisionType, PolicyDecision
from openagentpolicy.runtime.evaluator import PolicyEvaluator, build_evaluation_context
from openagentpolicy.runtime.events import PolicyEvent
from openagentpolicy.runtime.policy_field_validation import (
    UnresolvedPolicyFieldsError,
    validate_policy_fields,
)
from openagentpolicy.traces.recorder import TraceRecorder, create_trace_recorder

logger = logging.getLogger(__name__)


class UnenforceablePoliciesError(ValueError):
    """Raised when fail_on_unenforceable blocks startup."""


class PolicyRuntime:
    """Global policy runtime for event-driven enforcement."""

    def __init__(
        self,
        config: EngineConfig,
        *,
        base_path: Path | None = None,
    ) -> None:
        self.config = config
        self.base_path = base_path or Path.cwd()
        self._inventory_resolver = InventoryResolver(config.inventory, self.base_path)
        self._evaluator = PolicyEvaluator()
        self._redactor: PrivacyRedactor | None = None
        self._audit = AuditLogger(config.audit_log)
        self._trace_recorder: TraceRecorder | None = None

        self._inventory: Inventory | None = None
        self._policies: list[Policy] | None = None
        self._compile_results: list[PolicyCompileResult] = []
        self._load_errors: list[str] = []
        self._policy_provider: PolicyProvider | None = None
        self._bootstrap()

    @classmethod
    def from_config(cls, path: str | Path) -> PolicyRuntime:
        config_path = Path(path).resolve()
        return cls(load_config(config_path), base_path=config_base_path(config_path))

    @property
    def audit(self) -> AuditLogger:
        return self._audit

    @property
    def trace_recorder(self) -> TraceRecorder | None:
        return self._trace_recorder

    @property
    def inventory(self) -> Inventory:
        if self._inventory is None:
            self._inventory = Inventory()
        return self._inventory

    @property
    def policies(self) -> list[Policy]:
        if self._policies is None:
            self._policies = []
        return self._policies

    def reload(self) -> None:
        """Reload inventory and policies from configured providers."""
        self._bootstrap()

    def _bootstrap(self) -> None:
        self._load_errors = []
        self._inventory = self._load_inventory()
        self._inventory_resolver._cached = self._inventory
        self._redactor = PrivacyRedactor.from_config(
            self._inventory, self.config.privacy.redact_keys
        )
        self._audit = AuditLogger(self.config.audit_log, redactor=self._redactor)
        self._trace_recorder = create_trace_recorder(
            self.config.traces,
            self.base_path,
            redactor=self._redactor,
        )
        self._policy_provider = PolicyProvider(
            self.config.policies,
            self.base_path,
            inventory=self._inventory,
            compiler_enabled=self.config.compiler.enabled,
        )
        if self.config.policies.compile_on_startup:
            self._policies, self._compile_results = self._load_policies()
        else:
            self._policies = None
            self._compile_results = []

    def _load_inventory(self) -> Inventory:
        try:
            return self._inventory_resolver.preload()
        except Exception as exc:
            return self._handle_load_error("inventory", exc, Inventory())

    def _load_policies(self) -> tuple[list[Policy], list[PolicyCompileResult]]:
        try:
            assert self._policy_provider is not None
            policies, results = self._policy_provider.load_policies_with_results()
            self._raise_if_unenforceable(results)
            unresolved = validate_policy_fields(policies, self.inventory)
            if unresolved:
                error = UnresolvedPolicyFieldsError(unresolved)
                if self.config.enforcement.fail_on_unresolved_fields:
                    raise error
                for issue in unresolved:
                    logger.warning(issue.format())
            return policies, results
        except Exception as exc:
            if (
                self.config.enforcement.fail_on_unresolved_fields
                and isinstance(exc, UnresolvedPolicyFieldsError)
            ):
                raise
            if (
                self.config.enforcement.fail_on_unenforceable
                and isinstance(exc, UnenforceablePoliciesError)
            ):
                raise
            return self._handle_load_error("policies", exc, ([], []))

    def _raise_if_unenforceable(
        self, results: list[PolicyCompileResult]
    ) -> None:
        if not self.config.enforcement.fail_on_unenforceable:
            return
        app_env = (self.config.application.environment if self.config.application else None) or ""
        if app_env.lower() != "production":
            return
        bad = [
            result
            for result in results
            if result.compile_status in {
                CompileStatus.NOT_ENFORCEABLE,
                CompileStatus.NEEDS_REVIEW,
            }
        ]
        if not bad:
            return
        details = "; ".join(
            f"{r.policy_id}={r.compile_status.value}"
            + (f" ({r.message})" if r.message else "")
            for r in bad
        )
        raise UnenforceablePoliciesError(
            "Found unenforceable policies while fail_on_unenforceable=true in production: "
            f"{details}"
        )

    def _handle_load_error(self, resource: str, exc: Exception, fallback: Any) -> Any:
        message = f"Failed to load {resource}: {exc}"
        self._load_errors.append(message)
        on_error = self.config.enforcement.on_policy_error
        if on_error == OnPolicyError.RAISE:
            raise exc
        if on_error == OnPolicyError.BLOCK:
            logger.error(message)
            return fallback
        logger.warning("%s (on_policy_error=%s)", message, on_error.value)
        return fallback

    def _get_policies(self) -> list[Policy]:
        if self._policies is None:
            policies, results = self._load_policies()
            self._policies = policies
            self._compile_results = results
        return self._policies

    def process_event(
        self,
        event: PolicyEvent,
        *,
        enforce_inventory: bool = False,
    ) -> PolicyDecision:
        tool_id = event.tool_id or ""
        if enforce_inventory and tool_id:
            if self.inventory.get_tool(tool_id) is None:
                decision = PolicyDecision(
                    decision=DecisionType.BLOCK,
                    message=f"Unknown tool: {tool_id}",
                )
                self._record_event(event, decision)
                return decision

        trigger = _parse_trigger_event(event.event_type)
        if trigger is None:
            return PolicyDecision(
                decision=self.config.enforcement.default_action,
                message=f"Unknown event type: {event.event_type}",
            )

        context = build_evaluation_context(
            tool_args=event.tool_args,
            tool_result=event.tool_result,
            tool=_tool_context(self.inventory, tool_id),
            metadata=event.metadata,
            final_response=event.final_response,
            agent_id=event.agent_id,
        )
        decision = self._evaluator.evaluate(
            tool_id,
            context,
            self._get_policies(),
            trigger_event=trigger,
            agent_id=event.agent_id,
            default_decision=self.config.enforcement.default_action,
        )
        self._record_event(event, decision)
        return decision

    def _record_event(self, event: PolicyEvent, decision: PolicyDecision) -> None:
        if not self.config.enforcement.audit_enabled:
            return
        recorded = event.model_copy(
            update={
                "decision": decision.decision,
                "message": decision.message,
            }
        )
        self._audit.log(recorded)


class PolicyEngine(PolicyRuntime):
    """Backward-compatible alias for imperative tool-call checks."""

    def check_tool_call(
        self,
        tool_id: str,
        arguments: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        event = PolicyEvent(
            event_type=TriggerEvent.BEFORE_TOOL_CALL.value,
            tool_id=tool_id,
            tool_args=arguments or {},
            agent_id=self.config.runtime.default_agent_id,
            application_id=(
                self.config.application.id if self.config.application else None
            ),
        )
        return self.process_event(event, enforce_inventory=True)


def _parse_trigger_event(event_type: str) -> TriggerEvent | None:
    try:
        return TriggerEvent(event_type)
    except ValueError:
        return None


def _tool_context(inventory: Inventory, tool_id: str) -> dict[str, Any]:
    if not tool_id:
        return {}
    tool = inventory.get_tool(tool_id)
    if tool is None:
        return {}
    return {
        "id": tool.id,
        "name": tool.name,
        "risk_level": tool.risk_level.value if tool.risk_level else None,
        "side_effect": tool.side_effect,
    }


