"""Taiwan stock dashboard summary service.

Simplified version using Taiwan data sources (yfinance + TWSE).
"""
from tools.tw_price_data import get_stock_price
from tools.tw_financials import get_key_financials
from tools.tw_moving_averages import get_moving_average_signals
from tools.tw_news import get_stock_news


def build_dashboard_summary(ticker: str) -> dict:
    """Build Taiwan stock dashboard summary (simplified Trinity Hero).

    Args:
        ticker: Stock code (e.g., '2330')

    Returns:
        Dict with consolidated dashboard data
    """
    # Ensure .TW suffix
    if not ticker.endswith('.TW'):
        ticker_clean = ticker
        ticker_full = f"{ticker}.TW"
    else:
        ticker_clean = ticker[:-3]
        ticker_full = ticker

    # Fetch all data sources in parallel conceptually
    price_data = get_stock_price(ticker_clean)
    financials = get_key_financials(ticker_clean)
    technicals = get_moving_average_signals(ticker_clean)
    news = get_stock_news(ticker_clean, limit=5)

    # Build consolidated response
    return {
        "ticker": ticker_full,
        "summary": {
            "price_data": price_data,
            "financials": financials,
            "technicals": technicals,
            "recent_news": news.get("news", []) if "news" in news else [],
        },
        "data_quality": {
            "price_error": "error" in price_data,
            "financials_error": "error" in financials,
            "technicals_error": "error" in technicals,
        },
        "note": "Taiwan data from yfinance + TWSE API. Analyst coverage is limited."
    }


def build_market_overview() -> dict:
    """Build Taiwan market overview (TAIEX + OTC).

    Returns:
        Dict with market index data
    """
    import yfinance as yf

    try:
        # TAIEX (Taiwan Stock Exchange Weighted Index)
        taiex = yf.Ticker("^TWII")  # TAIEX code in yfinance
        taiex_info = taiex.fast_info

        return {
            "market": "Taiwan",
            "indices": {
                "TAIEX": {
                    "price": taiex_info.last_price,
                    "change_pct": ((taiex_info.last_price - taiex_info.previous_close) / taiex_info.previous_close * 100) if taiex_info.previous_close else None
                }
            },
            "note": "Limited Taiwan market data from yfinance"
        }
    except Exception as e:
        return {"error": str(e), "market": "Taiwan"}
