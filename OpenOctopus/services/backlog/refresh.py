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
    """Fetch live data for a single ticker. Returns a dict; sets 'error' on failure.

    Retries once on transient errors (SSL, connection reset, etc.).
    yfinance manages its own curl_cffi session internally.
    """
    import yfinance as yf  # lazy import to keep module load fast

    t = ticker.upper()
    last_exc: Exception | None = None

    for attempt in range(2):
        if attempt > 0:
            time.sleep(1.5)
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
            last_exc = e
            logger.warning("backlog: _fetch_one attempt %d failed for %s: %s", attempt + 1, t, e)

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
        "error": str(last_exc),
        "updated_at": datetime.now().isoformat()[:19],
    }


def fetch_backlog_data(tickers: list[str]) -> list[dict]:
    """Fetch live data for a list of tickers, up to 5 concurrent yfinance calls."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results_map: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_ticker = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(future_to_ticker):
            t = future_to_ticker[future]
            try:
                results_map[t] = future.result()
            except Exception as exc:
                results_map[t] = {
                    "ticker": t.upper(), "name": None, "sector": None,
                    "price": None, "vs_52w_low": None, "w52_chg_pct": None,
                    "w52_high": None, "w52_low": None, "ma10": None, "ma50": None,
                    "error": str(exc),
                    "updated_at": datetime.now().isoformat()[:19],
                }
    return [results_map.get(t, {"ticker": t.upper(), "error": "not fetched"}) for t in tickers]
