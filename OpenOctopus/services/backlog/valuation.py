"""Backlog valuation service.

Computes predicted stock prices based on yfinance TTM PE and EPS:
  e_price     = pe_ttm × eps_latest
  e_price_08  = e_price × 0.8          (bear case, 20% margin of safety)
  e_price_12  = e_price × 1.2          (bull case)
  e_price_cal = e_price × (1 + g + r) / (1 + mos)  (intrinsic value)
  a_price     = avg(e_price_cal, e_price_08)         (anchor average)

Default parameters:
  FORECAST_GROWTH = 0.10  (10% annual growth)
  MIN_RETURN      = 0.06  (6% minimum required return)
  MOS             = 0.25  (25% margin of safety)
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

FORECAST_GROWTH = 0.10
MIN_RETURN = 0.06
MOS = 0.25


def _r(v) -> float | None:
    try:
        return round(float(v), 2) if v is not None else None
    except Exception:
        return None


def fetch_valuation(ticker: str) -> dict:
    """Fetch valuation prices for a ticker using yfinance TTM PE and EPS."""
    import yfinance as yf  # lazy import

    t = ticker.upper()
    try:
        info = yf.Ticker(t).info or {}
    except Exception as exc:
        logger.warning("valuation: yfinance fetch failed for %s: %s", t, exc)
        return {
            "ticker": t,
            "pe_ttm": None,
            "eps_latest": None,
            "e_price": None,
            "e_price_08": None,
            "e_price_12": None,
            "e_price_cal": None,
            "a_price": None,
            "fetched_at": datetime.now().isoformat()[:19],
            "error": str(exc),
        }

    pe_ttm = info.get("trailingPE")
    eps_latest = info.get("trailingEps")

    e_price = e_price_08 = e_price_12 = e_price_cal = a_price = None
    error_msg = None

    try:
        pe = float(pe_ttm) if pe_ttm is not None else None
        eps = float(eps_latest) if eps_latest is not None else None

        if pe is not None and eps is not None and pe > 0 and eps > 0:
            e_price = pe * eps
            e_price_08 = e_price * 0.8
            e_price_12 = e_price * 1.2
            denom = 1.0 + MOS
            e_price_cal = e_price * (1.0 + FORECAST_GROWTH + MIN_RETURN) / denom
            a_price = (e_price_cal + e_price_08) / 2.0
        else:
            error_msg = "Insufficient data: pe_ttm or eps_latest unavailable or non-positive"
    except Exception as exc:
        error_msg = str(exc)
        logger.warning("valuation: calculation failed for %s: %s", t, exc)

    return {
        "ticker": t,
        "pe_ttm": _r(pe_ttm),
        "eps_latest": _r(eps_latest),
        "e_price": _r(e_price),
        "e_price_08": _r(e_price_08),
        "e_price_12": _r(e_price_12),
        "e_price_cal": _r(e_price_cal),
        "a_price": _r(a_price),
        "fetched_at": datetime.now().isoformat()[:19],
        "error": error_msg,
    }
