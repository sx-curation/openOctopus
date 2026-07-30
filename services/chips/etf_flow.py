"""
Chip Analysis - ETF Holders
FMP /v3/etf-holder (primary); no yfinance fallback available for ETF holder data.
"""
from __future__ import annotations

from datetime import datetime

import requests

from config import settings


def fetch_etf_holders(ticker: str) -> dict:
    t = ticker.upper()

    if not settings.FMP_API_KEY:
        return {
            "ticker": t,
            "etfs": [],
            "data_source": "none",
            "fetched_at": _now(),
            "error": "ETF holder data requires FMP API key",
        }

    try:
        url = f"{settings.FMP_BASE_URL}/api/v3/etf-holder/{t}"
        resp = requests.get(url, params={"apikey": settings.FMP_API_KEY}, timeout=10)

        if resp.status_code in (401, 403):
            return {
                "ticker": t,
                "etfs": [],
                "data_source": "none",
                "fetched_at": _now(),
                "error": "FMP subscription required for ETF holder data",
            }

        data = resp.json() if resp.status_code == 200 else []
        if not data:
            return {
                "ticker": t,
                "etfs": [],
                "data_source": "fmp",
                "fetched_at": _now(),
                "error": "No ETF holder data available",
            }

        etfs = sorted(data, key=lambda x: float(x.get("weightPercentage") or 0), reverse=True)[:10]
        processed = [
            {
                "name": e.get("asset") or e.get("etf") or "",
                "weight_pct": round(float(e.get("weightPercentage") or 0), 4),
                "shares": int(e.get("sharesNumber") or 0),
                "market_value": int(e.get("marketValue") or 0),
            }
            for e in etfs
        ]

        return {
            "ticker": t,
            "etfs": processed,
            "data_source": "fmp",
            "fetched_at": _now(),
            "error": None,
        }

    except Exception as e:
        return {
            "ticker": t,
            "etfs": [],
            "data_source": "none",
            "fetched_at": _now(),
            "error": str(e),
        }


def _now() -> str:
    return datetime.now().isoformat()[:19]
