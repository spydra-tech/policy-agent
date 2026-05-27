from __future__ import annotations

import contextvars
import inspect
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Generator, TypeVar, overload

from openagentpolicy.inventory.schema import ArgumentSchema, RiskLevel, Tool
from openagentpolicy.policies.schema import TriggerEvent
from openagentpolicy.runtime.decisions import DecisionType, PolicyDecision
from openagentpolicy.inventory.registry import POLICY_TOOL_ATTR
from openagentpolicy.runtime.events import PolicyEvent

if TYPE_CHECKING:
    from openagentpolicy.runtime.engine import PolicyRuntime

F = TypeVar("F", bound=Callable[..., Any])

logger = logging.getLogger(__name__)

_runtime: PolicyRuntime | None = None

_agent_session: contextvars.ContextVar["AgentSession | None"] = contextvars.ContextVar(
    "openagentpolicy_agent_session", default=None
)


@dataclass
class AgentSession:
    """Active agent identity and session metadata for policy evaluation."""

    agent_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


def get_agent_session() -> AgentSession | None:
    return _agent_session.get()


@contextmanager
def agent_session(
    agent_id: str,
    metadata: dict[str, Any] | None = None,
) -> Generator[AgentSession, None, None]:
    """Set the current agent and session metadata for nested tool/response checks."""
    session = AgentSession(agent_id=agent_id, metadata=dict(metadata or {}))
    token = _agent_session.set(session)
    try:
        yield session
    finally:
        _agent_session.reset(token)


class PolicyViolation(Exception):
    """Raised when a policy blocks tool execution."""

    def __init__(
        self,
        message: str | None = None,
        *,
        decision: PolicyDecision | None = None,
    ) -> None:
        self.decision = decision
        super().__init__(message or "Policy violation")


def configure(config_path: str | Path) -> PolicyRuntime:
    """Configure the global policy runtime from a config file."""
    from openagentpolicy.runtime.engine import PolicyRuntime

    global _runtime
    _runtime = PolicyRuntime.from_config(config_path)
    return _runtime


def get_runtime() -> PolicyRuntime:
    """Return the configured global policy runtime."""
    if _runtime is None:
        raise RuntimeError(
            "openagentpolicy is not configured; call configure() first"
        )
    return _runtime


def reset_runtime() -> None:
    """Reset the global runtime (for tests)."""
    global _runtime
    _runtime = None
    _agent_session.set(None)


def check_final_response(
    text: str,
    *,
    agent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Evaluate policies for an agent final response; return text if allowed."""
    runtime = get_runtime()
    event = _build_policy_event(
        runtime,
        event_type=TriggerEvent.BEFORE_FINAL_RESPONSE.value,
        agent_id=agent_id,
        metadata=metadata,
        final_response=text,
    )
    decision = runtime.process_event(event)
    _record_trace(
        runtime,
        event_type=TriggerEvent.BEFORE_FINAL_RESPONSE.value,
        tool_id="",
        tool_args={},
        decision=decision,
    )
    if decision.decision == DecisionType.BLOCK:
        raise PolicyViolation(decision.message, decision=decision)
    if decision.decision == DecisionType.WARN:
        logger.warning(
            "Policy warning for final response: %s",
            decision.message or "policy warn",
        )
    elif decision.decision == DecisionType.LOG_ONLY:
        logger.info(
            "Policy log_only for final response: %s",
            decision.message or "policy log",
        )
    return text


def check_final_response_any(
    response: Any,
    *,
    agent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Evaluate final response policies for common response container types."""
    if isinstance(response, str):
        return check_final_response(
            response,
            agent_id=agent_id,
            metadata=metadata,
        )

    key, text = _extract_response_text(response)
    safe = check_final_response(
        text,
        agent_id=agent_id,
        metadata=metadata,
    )
    return _replace_response_text(response, key, safe)


@overload
def policy_tool(func: F) -> F: ...


@overload
def policy_tool(
    *,
    id: str | None = None,
    name: str | None = None,
    description: str = "",
    risk_level: RiskLevel | str | None = None,
    side_effect: bool = False,
) -> Callable[[F], F]: ...


def policy_tool(
    func: F | None = None,
    *,
    id: str | None = None,
    name: str | None = None,
    description: str = "",
    risk_level: RiskLevel | str | None = None,
    side_effect: bool = False,
) -> F | Callable[[F], F]:
    """Mark and enforce policy on an agent tool function."""

    def decorator(fn: F) -> F:
        tool = _build_tool_definition(
            fn,
            tool_id=id,
            name=name,
            description=description,
            risk_level=risk_level,
            side_effect=side_effect,
        )
        wrapped = _wrap_with_enforcement(fn, tool)
        setattr(wrapped, POLICY_TOOL_ATTR, tool)
        return wrapped  # type: ignore[return-value]

    if func is not None:
        return decorator(func)
    return decorator


def get_tool_definition(func: Callable[..., Any]) -> Tool | None:
    from openagentpolicy.inventory.registry import get_tool_definition as _get

    return _get(func)


def _build_tool_definition(
    func: Callable[..., Any],
    *,
    tool_id: str | None,
    name: str | None,
    description: str,
    risk_level: RiskLevel | str | None,
    side_effect: bool,
) -> Tool:
    resolved_id = tool_id or name or func.__name__
    risk: RiskLevel | None = None
    if risk_level is not None:
        risk = RiskLevel(risk_level) if isinstance(risk_level, str) else risk_level
    return Tool(
        id=resolved_id,
        name=name or resolved_id,
        description=description or (func.__doc__ or "").strip(),
        side_effect=side_effect,
        risk_level=risk,
        arguments={
            param: ArgumentSchema(type="string")
            for param in _infer_parameters(func)
        },
    )


def _wrap_with_enforcement(func: Callable[..., Any], tool: Tool) -> Callable[..., Any]:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        runtime = get_runtime()
        bound_args = _bind_arguments(func, args, kwargs)

        before = _build_policy_event(
            runtime,
            event_type=TriggerEvent.BEFORE_TOOL_CALL.value,
            tool_id=tool.id,
            tool_args=bound_args,
        )
        before_decision = runtime.process_event(before)
        _record_trace(
            runtime,
            event_type=TriggerEvent.BEFORE_TOOL_CALL.value,
            tool_id=tool.id,
            tool_args=bound_args,
            decision=before_decision,
        )
        bound_args = _apply_before_decision(bound_args, before_decision)

        result = func(**bound_args)
        tool_result = _normalize_tool_result(result)

        after = _build_policy_event(
            runtime,
            event_type=TriggerEvent.AFTER_TOOL_CALL.value,
            tool_id=tool.id,
            tool_args=bound_args,
            tool_result=tool_result,
        )
        after_decision = runtime.process_event(after)
        _record_trace(
            runtime,
            event_type=TriggerEvent.AFTER_TOOL_CALL.value,
            tool_id=tool.id,
            tool_args=bound_args,
            tool_result=tool_result,
            decision=after_decision,
        )
        _apply_after_decision(after_decision)

        return result

    return wrapper


def _build_policy_event(
    runtime: PolicyRuntime,
    *,
    event_type: str,
    tool_id: str | None = None,
    tool_args: dict[str, Any] | None = None,
    tool_result: dict[str, Any] | None = None,
    agent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    final_response: str | None = None,
) -> PolicyEvent:
    session = get_agent_session()
    resolved_agent_id = agent_id
    if resolved_agent_id is None and session is not None:
        resolved_agent_id = session.agent_id
    if resolved_agent_id is None:
        resolved_agent_id = runtime.config.runtime.default_agent_id

    resolved_metadata: dict[str, Any] = {}
    if session is not None:
        resolved_metadata = dict(session.metadata)
    if metadata:
        resolved_metadata = {**resolved_metadata, **metadata}

    application_id = None
    if runtime.config.application is not None:
        application_id = runtime.config.application.id

    return PolicyEvent(
        event_type=event_type,
        application_id=application_id,
        agent_id=resolved_agent_id,
        tool_id=tool_id,
        tool_args=tool_args or {},
        tool_result=tool_result,
        metadata=resolved_metadata,
        final_response=final_response,
    )


def _bind_arguments(
    func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    signature = inspect.signature(func)
    bound = signature.bind_partial(*args, **kwargs)
    bound.apply_defaults()
    return dict(bound.arguments)


def _record_trace(
    runtime: PolicyRuntime,
    *,
    event_type: str,
    tool_id: str,
    tool_args: dict[str, Any],
    tool_result: dict[str, Any] | None = None,
    decision: PolicyDecision | None = None,
) -> None:
    recorder = runtime.trace_recorder
    if recorder is None or not recorder.enabled:
        return
    recorder.record_event(
        event_type=event_type,
        tool_id=tool_id,
        tool_args=tool_args,
        tool_result=tool_result,
        decision=decision,
    )


def _normalize_tool_result(result: Any) -> dict[str, Any] | None:
    if result is None:
        return None
    if isinstance(result, dict):
        return result
    return {"value": result}


def _apply_before_decision(
    bound_args: dict[str, Any], decision: PolicyDecision
) -> dict[str, Any]:
    if decision.decision == DecisionType.BLOCK:
        raise PolicyViolation(decision.message, decision=decision)
    if decision.decision == DecisionType.WARN:
        logger.warning(
            "Policy warning for tool call: %s",
            decision.message or "policy warn",
        )
    elif decision.decision == DecisionType.LOG_ONLY:
        logger.info(
            "Policy log_only for tool call: %s",
            decision.message or "policy log",
        )
    elif decision.decision == DecisionType.MODIFY_ARGS:
        if decision.modified_args:
            bound_args = {**bound_args, **decision.modified_args}
    elif decision.decision == DecisionType.REDIRECT_TOOL:
        raise PolicyViolation(
            decision.message or "redirect_tool not supported at runtime",
            decision=decision,
        )
    return bound_args


def _apply_after_decision(decision: PolicyDecision) -> None:
    if decision.decision == DecisionType.BLOCK:
        raise PolicyViolation(decision.message, decision=decision)
    if decision.decision == DecisionType.WARN:
        logger.warning(
            "Policy warning after tool call: %s",
            decision.message or "policy warn",
        )
    elif decision.decision == DecisionType.LOG_ONLY:
        logger.info(
            "Policy log_only after tool call: %s",
            decision.message or "policy log",
        )
    elif decision.decision in {
        DecisionType.MODIFY_ARGS,
        DecisionType.REDIRECT_TOOL,
    }:
        raise PolicyViolation(
            decision.message
            or f"{decision.decision.value} not supported after tool call",
            decision=decision,
        )


def _infer_parameters(func: Callable[..., Any]) -> list[str]:
    try:
        sig = inspect.signature(func)
        return [
            p.name
            for p in sig.parameters.values()
            if p.name not in {"self", "cls"}
        ]
    except (TypeError, ValueError):
        return []


_RESPONSE_TEXT_KEYS = ("content", "text", "final_answer", "response", "message")


def _extract_response_text(response: Any) -> tuple[str, str]:
    if isinstance(response, dict):
        for key in _RESPONSE_TEXT_KEYS:
            value = response.get(key)
            if isinstance(value, str):
                return key, value
        raise TypeError(
            "check_final_response_any expected dict with a string text field "
            f"one of {_RESPONSE_TEXT_KEYS}"
        )

    if hasattr(response, "model_dump") and callable(response.model_dump):
        data = response.model_dump()
        if isinstance(data, dict):
            for key in _RESPONSE_TEXT_KEYS:
                value = data.get(key)
                if isinstance(value, str):
                    return key, value
        raise TypeError(
            "check_final_response_any expected model with a string text field "
            f"one of {_RESPONSE_TEXT_KEYS}"
        )

    for key in _RESPONSE_TEXT_KEYS:
        value = getattr(response, key, None)
        if isinstance(value, str):
            return key, value

    raise TypeError(
        "check_final_response_any expected str, dict, or object/model with a "
        f"string text field one of {_RESPONSE_TEXT_KEYS}"
    )


def _replace_response_text(response: Any, key: str, safe_text: str) -> Any:
    if isinstance(response, dict):
        updated = dict(response)
        updated[key] = safe_text
        return updated

    if hasattr(response, "model_copy") and callable(response.model_copy):
        return response.model_copy(update={key: safe_text})

    if hasattr(response, key):
        setattr(response, key, safe_text)
        return response

    return safe_text
