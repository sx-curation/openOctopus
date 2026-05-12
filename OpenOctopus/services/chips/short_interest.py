"""
Chip Analysis - Short Interest Data
Extracts short interest metrics from yfinance info.
"""
from __future__ import annotations

from datetime import datetime


def fetch_short_interest(ticker: str) -> dict:
    import yfinance as yf

    t = ticker.upper()
    try:
        info = yf.Ticker(t).info or {}
    except Exception as e:
        return {"ticker": t, "error": str(e), "fetched_at": _now()}

    days_to_cover = _safe_float(info.get("shortRatio"))
    short_pct_float = _safe_float(info.get("shortPercentOfFloat"))
    shares_short = _safe_int(info.get("sharesShort"))
    shares_short_prior = _safe_int(info.get("sharesShortPriorMonth"))
    float_shares = _safe_int(info.get("floatShares"))

    # Month-over-month change
    if shares_short is not None and shares_short_prior and shares_short_prior > 0:
        mom_change_pct = round(
            (shares_short - shares_short_prior) / shares_short_prior * 100, 2
        )
    else:
        mom_change_pct = None

    # Float utilization
    if shares_short is not None and float_shares and float_shares > 0:
        float_utilization = round(shares_short / float_shares, 4)
    else:
        float_utilization = None

    # Signal logic
    if days_to_cover is None and short_pct_float is None:
        short_signal = "no_data"
    elif days_to_cover is not None and days_to_cover > 10:
        short_signal = "high"
    elif days_to_cover is not None and days_to_cover > 5:
        short_signal = "medium"
    else:
        short_signal = "low"

    return {
        "ticker": t,
        "days_to_cover": days_to_cover,
        "short_pct_float": short_pct_float,
        "shares_short": shares_short,
        "shares_short_prior_month": shares_short_prior,
        "float_shares": float_shares,
        "mom_change_pct": mom_change_pct,
        "float_utilization": float_utilization,
        "short_signal": short_signal,
        "fetched_at": _now(),
        "error": None,
    }


def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return round(f, 4) if f is not None else None
    except (TypeError, ValueError):
        return None


def _safe_int(v) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _now() -> str:
    return datetime.now().isoformat()[:19]
