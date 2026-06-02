"""Agent session helpers for CrewAI roles and scripted demos."""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from openagentpolicy import agent_session, check_final_response

F = TypeVar("F", bound=Callable[..., Any])


def run_as_agent(
    agent_id: str,
    fn: F,
    /,
    *args: Any,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    with agent_session(agent_id, metadata=metadata):
        return fn(*args, **kwargs)


def run_crew_role(
    agent_id: str,
    role_callable: Callable[[], Any],
    *,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Run a crew member's tool sequence under the correct agent identity."""
    with agent_session(agent_id, metadata=metadata):
        return role_callable()


def finalize_response(
    text: str,
    *,
    agent_id: str = "claims-adjuster-agent",
    metadata: dict[str, Any] | None = None,
) -> str:
    with agent_session(agent_id, metadata=metadata):
        return check_final_response(text)
