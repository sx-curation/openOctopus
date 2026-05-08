"""Backlog refresh service.

Fetches live market data for a list of tickers using yfinance.
Returns price, 52-week high/low, MA10, MA50, vs-52w-low %, and sector info.
"""

from __future__ import annotations

import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _fetch_one(ticker: str) -> dict:
    """Fetch live data for a single ticker. Returns a dict; sets 'error' on failure."""
    import yfinance as yf  # lazy import to keep module load fast

    t = ticker.upper()
    try:
        yticker = yf.Ticker(t)
        info = yticker.info or {}

        # Price fallback chain: regularMarketPrice → currentPrice → previousClose
        price = (
            info.get("regularMarketPrice")
            or info.get("currentPrice")
            or info.get("previousClose")
        )

        w52_high = info.get("fiftyTwoWeekHigh")
        w52_low = info.get("fiftyTwoWeekLow")

        # Compute vs_52w_low: (price - w52_low) / w52_low * 100
        vs_52w_low = None
        if price is not None and w52_low and w52_low > 0:
            vs_52w_low = round((price - w52_low) / w52_low * 100, 1)

        # Compute w52_chg_pct: (w52_high - w52_low) / w52_low * 100
        w52_chg_pct = None
        if w52_high is not None and w52_low and w52_low > 0:
            w52_chg_pct = round((w52_high - w52_low) / w52_low * 100, 1)

        # MA10 and MA50 — need 6 months of history for MA50
        ma10 = None
        ma50 = None
        try:
            hist = yticker.history(period="6mo", interval="1d")
            if not hist.empty and len(hist) >= 10:
                close = hist["Close"]
                ma10_series = close.rolling(10).mean()
                if not ma10_series.empty:
                    val = ma10_series.iloc[-1]
                    ma10 = round(float(val), 2) if val == val else None  # NaN check
                if len(hist) >= 50:
                    ma50_series = close.rolling(50).mean()
                    if not ma50_series.empty:
                        val = ma50_series.iloc[-1]
                        ma50 = round(float(val), 2) if val == val else None
        except Exception as e:
            logger.warning("backlog: history fetch failed for %s: %s", t, e)

        return {
            "ticker": t,
            "name": info.get("shortName") or info.get("longName") or t,
            "sector": info.get("sector") or "—",
            "price": round(float(price), 2) if price is not None else None,
            "vs_52w_low": vs_52w_low,
            "w52_chg_pct": w52_chg_pct,
            "w52_high": round(float(w52_high), 2) if w52_high is not None else None,
            "w52_low": round(float(w52_low), 2) if w52_low is not None else None,
            "ma10": ma10,
            "ma50": ma50,
            "error": None,
            "updated_at": datetime.now().isoformat()[:19],
        }
    except Exception as e:
        logger.warning("backlog: _fetch_one failed for %s: %s", t, e)
        return {
            "ticker": t,
            "name": None,
            "sector": None,
            "price": None,
            "vs_52w_low": None,
            "w52_chg_pct": None,
            "w52_high": None,
            "w52_low": None,
            "ma10": None,
            "ma50": None,
            "error": str(e),
            "updated_at": datetime.now().isoformat()[:19],
        }


def fetch_backlog_data(tickers: list[str]) -> list[dict]:
    """Fetch live data for a list of tickers, with 0.3s sleep between requests."""
    results = []
    for i, ticker in enumerate(tickers):
        results.append(_fetch_one(ticker))
        if i < len(tickers) - 1:
            time.sleep(0.3)
    return results
