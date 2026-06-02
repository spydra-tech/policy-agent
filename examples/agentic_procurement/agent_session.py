"""Helpers for running procurement tools and responses under an agent session."""

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


def finalize_response(
    text: str,
    *,
    agent_id: str = "procurement-agent",
    metadata: dict[str, Any] | None = None,
) -> str:
    with agent_session(agent_id, metadata=metadata):
        return check_final_response(text)
