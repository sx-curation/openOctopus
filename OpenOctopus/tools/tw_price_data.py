"""Taiwan stock price data using yfinance.

Taiwan stocks use .TW suffix in yfinance (e.g., 2330.TW for TSMC).
Reference: Colab CH-03 第 270-279 行
"""
import yfinance as yf


def get_stock_price(ticker: str) -> dict:
    """Get current price for Taiwan stock.

    Args:
        ticker: Stock code (e.g., '2330', '2330.TW')

    Returns:
        Dict with price data or error
    """
    try:
        # Ensure .TW suffix
        if not ticker.endswith('.TW'):
            ticker = f"{ticker}.TW"

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
            "currency": fi.currency or "TWD",
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}
