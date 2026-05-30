"""Helpers for running LangGraph nodes under an agent session."""

from __future__ import annotations

from typing import Any

from openagentpolicy import agent_session, check_final_response_any


def finalize_graph_output(
    state: dict[str, Any],
    *,
    message_key: str = "final_message",
) -> dict[str, Any]:
    """Apply before_final_response policies to the graph's user-visible message."""
    text = state.get(message_key)
    if text is None:
        return state
    agent_id = state.get("agent_id", "research-agent")
    metadata = state.get("metadata")
    safe = check_final_response_any(
        text,
        agent_id=agent_id,
        metadata=metadata,
    )
    return {**state, message_key: safe}


def with_agent_session(state: dict[str, Any]):
    """Context manager binding agent_id/metadata from graph state."""
    return agent_session(
        state.get("agent_id", "research-agent"),
        metadata=state.get("metadata"),
    )
