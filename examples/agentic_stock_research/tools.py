"""Stock research desk tools for the LangGraph policy demo."""

from __future__ import annotations

from openagentpolicy import policy_tool

# Mock market data (no external APIs required for the demo).
_MOCK_QUOTES: dict[str, dict[str, object]] = {
    "AAPL": {"symbol": "AAPL", "price": 198.45, "currency": "USD", "as_of": "demo"},
    "NVDA": {"symbol": "NVDA", "price": 118.20, "currency": "USD", "as_of": "demo"},
    "TSLA": {"symbol": "TSLA", "price": 245.10, "currency": "USD", "as_of": "demo"},
}

_MOCK_NEWS: dict[str, list[dict[str, str]]] = {
    "AAPL": [
        {"headline": "Apple services revenue beats estimates", "source": "demo-wire"},
        {"headline": "Supply chain stable ahead of product cycle", "source": "demo-wire"},
    ],
    "NVDA": [
        {"headline": "Data-center demand remains strong", "source": "demo-wire"},
    ],
}


@policy_tool(
    id="get_stock_quote",
    name="Get Stock Quote",
    description="Fetch a delayed quote for a ticker symbol",
    risk_level="low",
    side_effect=False,
)
def get_stock_quote(symbol: str) -> dict[str, object]:
    sym = symbol.upper().strip()
    base = _MOCK_QUOTES.get(sym, {"symbol": sym, "price": 100.0, "currency": "USD", "as_of": "demo"})
    return dict(base)


@policy_tool(
    id="search_financial_news",
    name="Search Financial News",
    description="Search recent headlines for a company or theme",
    risk_level="low",
    side_effect=False,
)
def search_financial_news(query: str) -> dict[str, object]:
    q = query.upper()
    for sym, items in _MOCK_NEWS.items():
        if sym in q:
            return {"query": query, "items": items}
    return {
        "query": query,
        "items": [{"headline": f"No demo headlines for {query!r}", "source": "demo-wire"}],
    }


@policy_tool(
    id="save_research_note",
    name="Save Research Note",
    description="Persist an internal research note",
    risk_level="medium",
    side_effect=True,
)
def save_research_note(symbol: str, note: str, conviction: str = "medium") -> dict[str, object]:
    return {
        "status": "saved",
        "symbol": symbol.upper(),
        "conviction": conviction,
        "note_preview": note[:120],
    }


@policy_tool(
    id="place_trade_order",
    name="Place Trade Order",
    description="Submit a buy or sell order",
    risk_level="high",
    side_effect=True,
)
def place_trade_order(symbol: str, quantity: float, side: str) -> dict[str, object]:
    return {
        "status": "submitted",
        "symbol": symbol.upper(),
        "quantity": quantity,
        "side": side.lower(),
        "order_id": f"demo-{symbol.upper()}-{int(quantity)}",
    }
