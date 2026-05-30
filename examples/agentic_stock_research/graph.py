"""LangGraph workflow for the stock research policy demo.

The graph models a short research → optional trade → report pipeline. Tool calls
inside nodes run under ``agent_session`` so ``@policy_tool`` enforcement applies.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from openagentpolicy.annotations import PolicyViolation

from agent_session import with_agent_session
from tools import get_stock_quote, place_trade_order, save_research_note, search_financial_news

try:
    from langgraph.graph import END, START, StateGraph
except ImportError as exc:  # pragma: no cover - optional demo dependency
    raise ImportError(
        "LangGraph is required for this example. Install with:\n"
        "  pip install -r requirements.txt"
    ) from exc


class StockResearchState(TypedDict, total=False):
    """State passed between LangGraph nodes."""

    agent_id: str
    metadata: dict[str, Any]
    symbol: str
    quantity: float
    attempt_trade: bool
    attempt_save_note: bool
    note: str
    quote: dict[str, object] | None
    news: dict[str, object] | None
    note_result: dict[str, object] | None
    trade_result: dict[str, object] | None
    final_message: str
    policy_error: str | None
    policy_blocked: bool


def gather_market_data(state: StockResearchState) -> StockResearchState:
    """Research node: quote + news (read-only tools)."""
    symbol = state["symbol"]
    with with_agent_session(state):
        quote = get_stock_quote(symbol=symbol)
        news = search_financial_news(query=f"{symbol} earnings outlook")
    return {
        **state,
        "quote": quote,
        "news": news,
    }


def persist_research_note(state: StockResearchState) -> StockResearchState:
    """Optional node: save an internal note (agent-gated by policy)."""
    if not state.get("attempt_save_note"):
        return state
    note = state.get("note") or f"Desk note on {state['symbol']}"
    try:
        with with_agent_session(state):
            result = save_research_note(
                symbol=state["symbol"],
                note=note,
                conviction="medium",
            )
        return {**state, "note_result": result, "policy_error": None, "policy_blocked": False}
    except PolicyViolation as exc:
        return {
            **state,
            "note_result": None,
            "policy_error": str(exc),
            "policy_blocked": True,
        }


def submit_trade(state: StockResearchState) -> StockResearchState:
    """Optional node: place a trade (high-risk, heavily policy-gated)."""
    if not state.get("attempt_trade"):
        return state
    try:
        with with_agent_session(state):
            result = place_trade_order(
                symbol=state["symbol"],
                quantity=state["quantity"],
                side="buy",
            )
        return {**state, "trade_result": result, "policy_error": None, "policy_blocked": False}
    except PolicyViolation as exc:
        return {
            **state,
            "trade_result": None,
            "policy_error": str(exc),
            "policy_blocked": True,
        }


def compose_report(state: StockResearchState) -> StockResearchState:
    """Build the user-visible summary (may be blocked at finalize)."""
    quote = state.get("quote") or {}
    price = quote.get("price", "?")
    sym = state.get("symbol", "?")
    trade = state.get("trade_result")
    err = state.get("policy_error")
    if err:
        body = (
            f"Research on {sym} at ${price}. "
            f"A policy blocked the requested action: {err}"
        )
    elif trade:
        body = (
            f"Research on {sym} at ${price}. "
            f"Trade submitted: {trade.get('order_id')} "
            f"({trade.get('quantity')} shares {trade.get('side')})."
        )
    else:
        body = f"Research on {sym} at ${price}. No trade was requested."
    return {**state, "final_message": body}


def _route_after_gather(state: StockResearchState) -> Literal["note", "trade", "report"]:
    if state.get("attempt_save_note"):
        return "note"
    if state.get("attempt_trade"):
        return "trade"
    return "report"


def build_stock_research_graph():
    """Compile the LangGraph workflow."""
    workflow: StateGraph = StateGraph(StockResearchState)
    workflow.add_node("gather", gather_market_data)
    workflow.add_node("note", persist_research_note)
    workflow.add_node("trade", submit_trade)
    workflow.add_node("report", compose_report)

    workflow.add_edge(START, "gather")
    workflow.add_conditional_edges(
        "gather",
        _route_after_gather,
        {"note": "note", "trade": "trade", "report": "report"},
    )
    workflow.add_edge("note", "report")
    workflow.add_edge("trade", "report")
    workflow.add_edge("report", END)
    return workflow.compile()
