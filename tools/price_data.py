import yfinance as yf

from tools.base import BaseTool
from tools.resilience import retry_with_backoff, with_timeout
from data_sources.market import stooq


class PriceDataTool(BaseTool):
    """Fetch current stock price — yfinance primary, stooq fallback."""

    name = "get_stock_price"
    description = (
        "Returns current price and basic market data for a given ticker symbol. "
        "Uses yfinance with automatic stooq fallback."
    )

    def execute(self, input: dict) -> dict:
        ticker = input.get("ticker", "")
        if not ticker:
            return {"error": "ticker_required"}

        ticker = ticker.upper()

        # --- Primary: yfinance with retry + timeout ---
        try:
            result = retry_with_backoff(
                lambda: with_timeout(lambda: self._yfinance_quote(ticker), seconds=30),
                max_retries=3,
                backoff_base=1.0,
            )
            if "error" not in result:
                return result
            yf_error = result.get("error")
        except Exception as exc:
            yf_error = str(exc)

        # --- Fallback: stooq ---
        try:
            stooq_result = stooq.get_quote(ticker)
            if "error" not in stooq_result and stooq_result.get("price") is not None:
                return {
                    "ticker": ticker,
                    "price": stooq_result.get("price"),
                    "change_pct": stooq_result.get("change_pct"),
                    "volume": stooq_result.get("volume"),
                    "market_cap": None,
                    "week_52_high": None,
                    "week_52_low": None,
                    "currency": stooq_result.get("currency"),
                    "fallback_source": "stooq",
                }
        except Exception:
            pass

        return {"error": "all_sources_failed", "ticker": ticker, "yfinance_error": yf_error}

    @staticmethod
    def _yfinance_quote(ticker: str) -> dict:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        price = fi.last_price
        if price is None:
            return {"error": "ticker_not_found", "ticker": ticker}
        prev_close = fi.previous_close or price
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else None
        return {
            "ticker": ticker,
            "price": round(price, 2),
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "volume": fi.three_month_average_volume,
            "market_cap": fi.market_cap,
            "week_52_high": fi.year_high,
            "week_52_low": fi.year_low,
            "currency": fi.currency,
        }


# ---------------------------------------------------------------------------
# Module-level wrapper — preserves backward compatibility with all callers
# ---------------------------------------------------------------------------
_tool = PriceDataTool()


def get_stock_price(ticker: str) -> dict:
    """Backward-compatible wrapper around PriceDataTool.execute()."""
    return _tool.execute({"ticker": ticker})
