"""Backlog valuation service.

Computes predicted stock prices based on yfinance TTM PE and EPS:
  e_price     = pe_ttm × eps_latest
  e_price_08  = e_price × 0.8          (bear case, 20% margin of safety)
  e_price_12  = e_price × 1.2          (bull case)
  e_price_cal = e_price × (1 + g + r) / (1 + mos)  (intrinsic value)
  e_price_2u  = eps_latest × (pe_min + pe_step × 2) (2-step PE recovery)
  a_price     = mean(e_price_cal, e_price_2u, e_price_08)  (anchor average)

Default parameters:
  FORECAST_GROWTH = 0.10  (10% annual growth)
  MIN_RETURN      = 0.06  (6% minimum required return)
  MOS             = 0.25  (25% margin of safety)

PE range: pe_min / pe_max from up to 5 years of annual year-end PE values.
  pe_step = (pe_max - pe_min) / 5
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


_EPS_KEYS = ("Diluted EPS", "Basic EPS", "EPS", "Diluted Eps", "Basic Eps")


def _find_eps_key(income) -> str | None:
    """Return the first EPS row name found in the income DataFrame index."""
    for key in _EPS_KEYS:
        if key in income.index:
            return key
    logger.warning(
        "valuation: no EPS row found in financials; available rows: %s",
        list(income.index),
    )
    return None


def _fetch_5yr_pe_range(stock) -> tuple[float | None, float | None]:
    """Return (pe_min, pe_max) from up to 5 annual year-end PE values."""
    try:
        import pandas as pd
        income = stock.financials
        hist = stock.history(period="5y", interval="1mo")
        if income is None or income.empty or hist.empty:
            return None, None

        eps_key = _find_eps_key(income)
        if eps_key is None:
            return None, None

        pe_list = []
        for col in list(income.columns)[:5]:
            try:
                eps_row = float(income.loc[eps_key, col])
            except Exception:
                continue
            if eps_row <= 0:
                continue
            col_ts = pd.Timestamp(col)
            if col_ts.tzinfo is not None:
                col_ts = col_ts.tz_convert(None)
            hist_idx = hist.index.tz_convert(None) if hist.index.tz is not None else hist.index
            nearby = hist[hist_idx <= col_ts + pd.DateOffset(months=3)]
            if nearby.empty:
                continue
            price = float(nearby["Close"].iloc[-1])
            pe = price / eps_row
            if 0 < pe < 500:
                pe_list.append(pe)
        if len(pe_list) >= 2:
            return round(min(pe_list), 1), round(max(pe_list), 1)
    except Exception as exc:
        logger.warning("valuation: pe range failed: %s", exc)
    return None, None


def fetch_valuation(ticker: str) -> dict:
    """Fetch valuation prices for a ticker using yfinance TTM PE and EPS."""
    import yfinance as yf  # lazy import

    t = ticker.upper()
    try:
        stock = yf.Ticker(t)
        info = stock.info or {}
    except Exception as exc:
        logger.warning("valuation: yfinance fetch failed for %s: %s", t, exc)
        return {
            "ticker": t,
            "pe_ttm": None, "eps_latest": None,
            "e_price": None, "e_price_08": None, "e_price_12": None,
            "e_price_cal": None, "e_price_2u": None,
            "pe_min": None, "pe_max": None, "pe_step": None,
            "a_price": None,
            "fetched_at": datetime.now().isoformat()[:19],
            "error": str(exc),
        }

    pe_ttm = info.get("trailingPE")
    eps_latest = info.get("trailingEps")

    e_price = e_price_08 = e_price_12 = e_price_cal = e_price_2u = a_price = None
    pe_min = pe_max = pe_step = None
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

            # 5-year PE range for e_price_2u
            pe_min, pe_max = _fetch_5yr_pe_range(stock)
            if pe_min is not None and pe_max is not None:
                pe_step = round((pe_max - pe_min) / 5, 2)
                e_price_2u = eps * (pe_min + pe_step * 2)

            # a_price = mean of available components
            _pool = [("e_cal", e_price_cal), ("e_2u", e_price_2u), ("e_08", e_price_08)]
            components_used = [k for k, v in _pool if v is not None]
            missing_components = [k for k, v in _pool if v is None]
            vals = [v for _, v in _pool if v is not None]
            a_price = sum(vals) / len(vals) if vals else None
        else:
            error_msg = "Insufficient data: pe_ttm or eps_latest unavailable or non-positive"
            components_used = []
            missing_components = ["e_cal", "e_2u", "e_08"]
    except Exception as exc:
        error_msg = str(exc)
        logger.warning("valuation: calculation failed for %s: %s", t, exc)
        components_used = []
        missing_components = ["e_cal", "e_2u", "e_08"]

    return {
        "ticker": t,
        "pe_ttm": _r(pe_ttm),
        "eps_latest": _r(eps_latest),
        "e_price": _r(e_price),
        "e_price_08": _r(e_price_08),
        "e_price_12": _r(e_price_12),
        "e_price_cal": _r(e_price_cal),
        "e_price_2u": _r(e_price_2u),
        "pe_min": _r(pe_min),
        "pe_max": _r(pe_max),
        "pe_step": _r(pe_step),
        "a_price": _r(a_price),
        "a_price_count": len(components_used),
        "missing_components": missing_components,
        "fetched_at": datetime.now().isoformat()[:19],
        "error": error_msg,
    }
