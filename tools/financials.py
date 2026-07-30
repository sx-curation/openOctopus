import yfinance as yf

from tools.base import BaseTool
from tools.resilience import retry_with_backoff, with_timeout


class FinancialsTool(BaseTool):
    """Fetch core financial metrics for a ticker via yfinance."""

    name = "get_key_financials"
    description = (
        "Returns key financial metrics (valuation, margins, balance sheet, returns) "
        "for a given ticker symbol."
    )

    def execute(self, input: dict) -> dict:
        ticker = input.get("ticker", "")
        if not ticker:
            return {"error": "ticker_required"}
        try:
            return retry_with_backoff(
                lambda: with_timeout(lambda: _fetch_financials(ticker.upper()), seconds=30),
                max_retries=3,
                backoff_base=1.0,
            )
        except Exception as exc:
            return {"error": str(exc), "ticker": ticker.upper()}


# ---------------------------------------------------------------------------
# Core fetch logic (extracted so _tool wrapper can call it too)
# ---------------------------------------------------------------------------

def _fetch_financials(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        info = t.info

        if not info or info.get("symbol") is None:
            return {"error": "ticker_not_found", "ticker": ticker}

        def _fmt_pct(v):
            return round(v * 100, 2) if v is not None else None

        def _fmt_b(v):
            if v is None:
                return None
            return round(v / 1e9, 2)

        return {
            "ticker": ticker,
            "company_name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "pe_ratio_trailing": info.get("trailingPE"),
            "pe_ratio_forward": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "price_to_sales": info.get("priceToSalesTrailing12Months"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
            "eps_ttm": info.get("trailingEps"),
            "eps_forward": info.get("forwardEps"),
            "revenue_ttm_billions": _fmt_b(info.get("totalRevenue")),
            "revenue_growth_yoy_pct": _fmt_pct(info.get("revenueGrowth")),
            "earnings_growth_yoy_pct": _fmt_pct(info.get("earningsGrowth")),
            "gross_margin_pct": _fmt_pct(info.get("grossMargins")),
            "operating_margin_pct": _fmt_pct(info.get("operatingMargins")),
            "net_margin_pct": _fmt_pct(info.get("profitMargins")),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),
            "return_on_equity_pct": _fmt_pct(info.get("returnOnEquity")),
            "return_on_assets_pct": _fmt_pct(info.get("returnOnAssets")),
            "free_cash_flow_billions": _fmt_b(info.get("freeCashflow")),
            "dividend_yield_pct": (
                round(info["dividendRate"] / info["currentPrice"] * 100, 2)
                if info.get("dividendRate") and info.get("currentPrice")
                else None
            ),
            "payout_ratio_pct": _fmt_pct(info.get("payoutRatio")),
            "shares_outstanding_billions": _fmt_b(info.get("sharesOutstanding")),
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ---------------------------------------------------------------------------
# Module-level singleton + backward-compatible wrapper
# ---------------------------------------------------------------------------
_tool = FinancialsTool()


def get_key_financials(ticker: str) -> dict:
    """Backward-compatible wrapper around FinancialsTool.execute()."""
    return _tool.execute({"ticker": ticker})
