import yfinance as yf


def get_stock_price(ticker: str) -> dict:
    """
    Returns current price and basic market data for the given ticker.
    Uses yfinance fast_info for speed.
    """
    try:
        t = yf.Ticker(ticker.upper())
        fi = t.fast_info

        price = fi.last_price
        if price is None:
            return {"error": "ticker_not_found", "ticker": ticker}

        prev_close = fi.previous_close or price
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else None

        return {
            "ticker": ticker.upper(),
            "price": round(price, 2),
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "volume": fi.three_month_average_volume,
            "market_cap": fi.market_cap,
            "week_52_high": fi.year_high,
            "week_52_low": fi.year_low,
            "currency": fi.currency,
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}
