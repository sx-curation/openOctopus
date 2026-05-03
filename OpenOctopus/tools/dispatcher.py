"""
Routes tool_name → handler function and returns a JSON-serialisable result dict.
Results are cached in-memory with a TTL to avoid redundant API calls.
"""
from tools.price_data import get_stock_price
from tools.moving_averages import get_moving_average_signals
from tools.financials import get_key_financials
from tools.analyst_estimates import get_analyst_estimates
from tools.earnings_transcript import get_earnings_transcript
from tools.sec_filings import get_sec_filing_summary
from tools.sec_8k_events import get_recent_8k_events
from utils import cache
from config import settings

# Policy Monitoring Agent - lazy import to avoid startup cost when not used
def _query_policy_updates(inp: dict) -> dict:
    from agent.policy_monitoring import PolicyMonitoringAgent

    agent = PolicyMonitoringAgent()
    events = agent.query_updates(
        jurisdiction=inp.get("jurisdiction", "ALL"),
        keyword=inp["keyword"],
        from_date=inp.get("from_date", "2024-01-01"),
        to_date=inp.get("to_date", "2099-12-31"),
        limit=int(inp.get("limit", 10)),
        sources=inp.get("sources"),
    )
    return {
        "events": [e.to_dict() for e in events],
        "count": len(events),
        "sources_queried": inp.get("sources") or ["EUR_LEX", "FEDERAL_REGISTER", "SEC"],
    }

_REGISTRY = {
    "query_policy_updates": _query_policy_updates,
    "get_stock_price": lambda inp: get_stock_price(inp["ticker"]),
    "get_moving_average_signals": lambda inp: get_moving_average_signals(
        inp["ticker"], inp.get("lookback_days", 250)
    ),
    "get_key_financials": lambda inp: get_key_financials(inp["ticker"]),
    "get_analyst_estimates": lambda inp: get_analyst_estimates(inp["ticker"]),
    "get_earnings_transcript": lambda inp: get_earnings_transcript(
        inp["ticker"], inp.get("year"), inp.get("quarter")
    ),
    "get_sec_filing_summary": lambda inp: get_sec_filing_summary(
        inp["ticker"], inp.get("filing_type", "10-K")
    ),
    "get_recent_8k_events": lambda inp: get_recent_8k_events(
        inp["ticker"], inp.get("lookback_count", 20)
    ),
}

# Tools where caching is appropriate (exclude transcript/SEC which are rarely called twice)
_CACHEABLE = {
    "get_stock_price",
    "get_moving_average_signals",
    "get_key_financials",
    "get_analyst_estimates",
}


def dispatch(tool_name: str, tool_input: dict) -> dict:
    """Execute a tool by name and return a result dict."""
    handler = _REGISTRY.get(tool_name)
    if handler is None:
        return {"error": f"Unknown tool: {tool_name}"}

    ticker = tool_input.get("ticker", "")

    # Check cache
    if tool_name in _CACHEABLE and ticker:
        cached = cache.get(tool_name, ticker)
        if cached is not None:
            return cached

    try:
        result = handler(tool_input)
    except Exception as e:
        return {"error": f"Tool '{tool_name}' raised an exception: {e}"}

    # Store in cache
    if tool_name in _CACHEABLE and ticker and "error" not in result:
        cache.set(tool_name, ticker, result, ttl=settings.CACHE_TTL_SECONDS)

    return result
