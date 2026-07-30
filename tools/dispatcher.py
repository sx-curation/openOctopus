"""
Routes tool_name → BaseTool.execute() and caches results via CacheManager.

Cache tiers:
  L1 (TTL 300s) : get_stock_price, get_key_financials, get_analyst_estimates,
                  get_moving_average_signals
  L2 (TTL 86400s): get_earnings_transcript, get_sec_filing_summary,
                   get_recent_8k_events
  No cache       : query_policy_updates (always live)
"""
from tools.base import BaseTool
from tools.price_data import PriceDataTool
from tools.moving_averages import get_moving_average_signals
from tools.financials import FinancialsTool
from tools.analyst_estimates import EstimatesTool
from tools.earnings_transcript import EarningsTranscriptTool
from tools.sec_filings import SecFilingsTool
from tools.sec_8k_events import Sec8kTool
from utils.cache_manager import cache


# ---------------------------------------------------------------------------
# Policy tool (not a BaseTool — keep as callable, no caching)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Moving-averages shim (not yet a BaseTool — wrap in an adapter)
# ---------------------------------------------------------------------------

class _MovingAverageTool(BaseTool):
    name = "get_moving_average_signals"
    description = "Returns moving average signals for a ticker."

    def execute(self, input: dict) -> dict:
        return get_moving_average_signals(
            input.get("ticker", ""),
            input.get("lookback_days", 250),
        )


# ---------------------------------------------------------------------------
# Tool registry  — keyed by tool name
# ---------------------------------------------------------------------------

_TOOLS: dict[str, BaseTool] = {
    "get_stock_price": PriceDataTool(),
    "get_moving_average_signals": _MovingAverageTool(),
    "get_key_financials": FinancialsTool(),
    "get_analyst_estimates": EstimatesTool(),
    "get_earnings_transcript": EarningsTranscriptTool(),
    "get_sec_filing_summary": SecFilingsTool(),
    "get_recent_8k_events": Sec8kTool(),
}

# Cache layer assignment: tool_name → (layer, ttl)
_L1_TOOLS = {"get_stock_price", "get_key_financials", "get_analyst_estimates", "get_moving_average_signals"}
_L2_TOOLS = {"get_earnings_transcript", "get_sec_filing_summary", "get_recent_8k_events"}

_L1_TTL = 300
_L2_TTL = 86400


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

def dispatch(tool_name: str, tool_input: dict) -> dict:
    """Execute a tool by name and return a JSON-serialisable result dict."""

    # Policy tool — not a BaseTool, no caching
    if tool_name == "query_policy_updates":
        try:
            return _query_policy_updates(tool_input)
        except Exception as exc:
            return {"error": f"Tool 'query_policy_updates' raised: {exc}"}

    tool = _TOOLS.get(tool_name)
    if tool is None:
        return {"error": f"Unknown tool: {tool_name}"}

    ticker = tool_input.get("ticker", "")
    layer = 1 if tool_name in _L1_TOOLS else (2 if tool_name in _L2_TOOLS else None)

    # Cache read
    if layer and ticker:
        cached = cache.get(layer, tool_name, ticker)
        if cached is not None:
            return cached

    try:
        result = tool.execute(tool_input)
    except Exception as exc:
        return {"error": f"Tool '{tool_name}' raised an exception: {exc}"}

    # Cache write (only on success)
    if layer and ticker and "error" not in result:
        ttl = _L1_TTL if layer == 1 else _L2_TTL
        try:
            cache.set(layer, tool_name, ticker, result, ttl=ttl)
        except Exception:
            pass  # cache write failure is non-fatal

    return result
