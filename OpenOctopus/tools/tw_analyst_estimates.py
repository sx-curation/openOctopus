"""Taiwan stock analyst estimates using yfinance.

Note: Taiwan analyst data availability is limited compared to US stocks.
"""
import yfinance as yf
from typing import Dict, Any


def get_analyst_estimates(ticker: str) -> Dict[str, Any]:
    """Get analyst estimates for Taiwan stock.

    Args:
        ticker: Stock code (e.g., '2330', '2330.TW')

    Returns:
        Dict with analyst data or note about limited availability
    """
    try:
        # Ensure .TW suffix
        if not ticker.endswith('.TW'):
            ticker = f"{ticker}.TW"

        t = yf.Ticker(ticker)
        info = t.info

        if not info or info.get("symbol") is None:
            return {"error": "ticker_not_found", "ticker": ticker}

        # Taiwan stocks have limited analyst coverage in yfinance
        return {
            "ticker": ticker,
            "target_price": info.get("targetPrice"),
            "target_price_high": info.get("targetHighPrice"),
            "target_price_low": info.get("targetLowPrice"),
            "number_of_analysts": info.get("numberOfAnalysts"),
            "recommendation": info.get("recommendationKey"),  # 'buy', 'hold', 'sell'
            "eps_estimate": info.get("epsTrailingTwelveMonths"),
            "note": "Taiwan analyst coverage is limited; data may be sparse"
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker, "note": "Limited analyst data for Taiwan stocks"}
