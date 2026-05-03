"""Taiwan market overview service.

TAIEX and OTC market data.
"""
import yfinance as yf


def build_market_overview() -> dict:
    """Build Taiwan market overview.

    Returns:
        Dict with TAIEX and OTC data
    """
    try:
        # TAIEX (Taiwan Weighted Index)
        taiex = yf.Ticker("^TWII")
        taiex_hist = taiex.history(period="30d")

        if taiex_hist.empty:
            return {"error": "Unable to fetch TAIEX data", "market": "Taiwan"}

        taiex_price = taiex_hist["Close"].iloc[-1]
        taiex_prev = taiex_hist["Close"].iloc[-2] if len(taiex_hist) > 1 else taiex_price
        taiex_change_pct = ((taiex_price - taiex_prev) / taiex_prev * 100) if taiex_prev else 0

        # Generate simple sparkline (last 30 days)
        sparkline = taiex_hist["Close"].tail(30).tolist()

        return {
            "market": "Taiwan",
            "indices": [
                {
                    "name": "TAIEX",
                    "symbol": "^TWII",
                    "price": round(taiex_price, 2),
                    "change_pct": round(taiex_change_pct, 2),
                    "sparkline": [round(x, 2) for x in sparkline]
                }
            ],
            "note": "Data from yfinance; OTC (OTC:^TAIEX) coverage is limited"
        }
    except Exception as e:
        return {"error": str(e), "market": "Taiwan"}
