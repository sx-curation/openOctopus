"""Taiwan stock dashboard summary service.

Integrates database layer (tw_stock.db) with yfinance and TWSE API.
"""
import os
from pathlib import Path
from tools.tw_price_data import get_stock_price
from tools.tw_financials import get_key_financials
from tools.tw_moving_averages import get_moving_average_signals
from tools.tw_news import get_stock_news
from data_sources.tw.collector import collect_and_store_tw_stock_data, get_tw_stock_summary
from data_sources.tw.db import TaiwanStockDB


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

    # Determine database path
    app_root = Path(__file__).parent.parent.parent.parent
    db_path = app_root / 'tw_stock.db'

    # Try to collect/update data (this also stores in DB)
    collection_result = collect_and_store_tw_stock_data(ticker_clean, str(db_path), period='1y')

    # Fetch all data sources
    price_data = get_stock_price(ticker_clean)
    financials = get_key_financials(ticker_clean)
    technicals = get_moving_average_signals(ticker_clean)
    news = get_stock_news(ticker_clean, limit=5)

    # Get summary from database (includes 52-week stats)
    db_summary = get_tw_stock_summary(ticker_clean, str(db_path))

    # Build consolidated response
    return {
        "ticker": ticker_full,
        "summary": {
            "company_name": financials.get('company_name', ticker_clean),
            "price_data": {
                **price_data,
                "week_52_high": db_summary.get('week_52_high'),
                "week_52_low": db_summary.get('week_52_low'),
            },
            "financials": financials,
            "technicals": technicals,
            "recent_news": news.get("news", []) if "news" in news else [],
        },
        "data_quality": {
            "price_error": "error" in price_data,
            "financials_error": "error" in financials,
            "technicals_error": "error" in technicals,
            "db_available": not ("error" in db_summary),
            "data_points_stored": db_summary.get('price_data_points', 0),
        },
        "note": "Taiwan data from yfinance + TWSE API + SQLite database. Analyst coverage is limited.",
        "_collection_status": collection_result.get('status', 'unknown')
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
