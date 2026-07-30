"""
Chip Analysis - Institutional Holdings
FMP /v3/institutional-holder (primary) with yfinance institutional_holders fallback.
"""
from __future__ import annotations

from datetime import datetime

import requests

from config import settings


def fetch_institutional(ticker: str) -> dict:
    t = ticker.upper()
    USE_FMP = bool(settings.FMP_API_KEY)

    if not USE_FMP:
        return _fetch_yfinance(t)

    try:
        url = f"{settings.FMP_BASE_URL}/api/v3/institutional-holder/{t}"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=10)

        if resp.status_code in (401, 403):
            return _fetch_yfinance(t, fmp_auth_failed=True)
        if resp.status_code == 404 or not resp.json():
            return _empty(t, "No institutional data from FMP")

        data = resp.json()
        holders = sorted(data, key=lambda x: x.get("shares", 0) or 0, reverse=True)[:15]

        processed = []
        for h in holders:
            shares = h.get("shares") or 0
            change = h.get("change") or 0
            prev_shares = shares - change
            change_pct = round(change / prev_shares * 100, 2) if prev_shares > 0 else None
            processed.append(
                {
                    "holder": h.get("holder", ""),
                    "shares": int(shares),
                    "change": int(change),
                    "change_pct": change_pct,
                    "date_reported": h.get("dateReported", ""),
                }
            )

        # Net signal: sum of buy changes vs sell changes
        buys = sum(h["change"] for h in processed if h["change"] > 0)
        sells = abs(sum(h["change"] for h in processed if h["change"] < 0))
        if buys == 0 and sells == 0:
            net_signal = "neutral"
        elif buys > sells:
            net_signal = "buy"
        else:
            net_signal = "sell"

        return {
            "ticker": t,
            "holders": processed,
            "net_signal": net_signal,
            "data_source": "fmp",
            "fetched_at": _now(),
            "error": None,
        }

    except Exception as e:
        return _fetch_yfinance(t, fallback_reason=str(e))


def _fetch_yfinance(t: str, fmp_auth_failed: bool = False, fallback_reason: str = "") -> dict:
    import yfinance as yf

    try:
        yticker = yf.Ticker(t)
        df = yticker.institutional_holders
    except Exception as e:
        return _empty(t, f"yfinance error: {e}")

    if df is None or df.empty:
        return _empty(t, "No institutional data available")

    processed = []
    for _, row in df.iterrows():
        processed.append(
            {
                "holder": str(row.get("Holder") or row.get("Institution") or ""),
                "shares": int(row.get("Shares") or 0),
                "change": None,  # yfinance doesn't provide QoQ change
                "change_pct": None,
                "date_reported": str(row.get("Date Reported") or "")[:10],
                "pct_held": round(float(row.get("% Out") or row.get("pctHeld") or 0) * 100, 2),
            }
        )

    reason = "FMP key not configured" if not fmp_auth_failed else "FMP subscription required"
    if fallback_reason:
        reason = fallback_reason

    return {
        "ticker": t,
        "holders": processed[:15],
        "net_signal": "no_data",
        "data_source": "yfinance",
        "fallback_reason": reason,
        "fetched_at": _now(),
        "error": None,
    }


def _empty(t: str, msg: str) -> dict:
    return {
        "ticker": t,
        "holders": [],
        "net_signal": "no_data",
        "data_source": "none",
        "fetched_at": _now(),
        "error": msg,
    }


def _now() -> str:
    return datetime.now().isoformat()[:19]
