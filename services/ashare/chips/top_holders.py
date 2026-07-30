"""Top 10 floating shareholders (十大流通股东) for A-shares.

Uses AKShare stock_gdfx_free_top_10_em(symbol, date).
Data is quarterly — tries the last 4 quarters.
"""
from __future__ import annotations

import logging
from datetime import date

from services.ashare import strip_suffix

logger = logging.getLogger(__name__)

# Recent quarter-end dates to try (newest first)
_QUARTER_ENDS = ["20241231", "20240930", "20240630", "20240331", "20231231"]


def _exchange_prefix(ticker: str) -> str:
    return "sh" if ticker.upper().endswith(".SH") else "sz"


def fetch_top_holders(ticker: str) -> dict:
    """Return top 10 floating shareholders for ticker.

    Response schema aligns with fetch_institutional() for /api/chips/institutional:
        holders:      list of holder dicts
        net_signal:   "buy" | "sell" | "neutral" | "no_data"
        data_source:  str
        report_date:  ISO date string (quarterly)
    """
    import akshare as ak

    code = strip_suffix(ticker)
    symbol = _exchange_prefix(ticker) + code  # e.g. "sz002384", "sh600519"

    for qdate in _QUARTER_ENDS:
        try:
            df = ak.stock_gdfx_free_top_10_em(symbol=symbol, date=qdate)
        except Exception as e:
            logger.debug("top_holders: %s date=%s: %s", ticker, qdate, e)
            continue

        if df is None or df.empty:
            continue

        # Columns: 排名 股东名称 股东性质 股份类型 持股数 占总流通股比例(%) 变动 变动数量
        # col 0=rank, 1=name, 2=type, 3=share_type, 4=shares, 5=pct, 6=change_flag, 7=change_qty
        report_date = qdate[:4] + "-" + qdate[4:6] + "-" + qdate[6:]
        holders = []
        for _, row in df.iterrows():
            holders.append({
                "holder":        str(row.iloc[1]) if len(row) > 1 else "",
                "holder_type":   str(row.iloc[2]) if len(row) > 2 else "",
                "shares":        _safe_float(row.iloc[4]) if len(row) > 4 else None,
                "pct":           _safe_float(row.iloc[5]) if len(row) > 5 else None,
                "change":        _safe_float_or_none(row.iloc[7]) if len(row) > 7 else None,
                "change_flag":   str(row.iloc[6]) if len(row) > 6 else "",
                "date_reported": report_date,
            })

        if holders:
            return {
                "holders":     holders,
                "net_signal":  _net_signal(holders),
                "data_source": "akshare",
                "report_date": report_date,
            }

    return {"holders": [], "net_signal": "no_data", "data_source": "none"}


def _net_signal(holders: list[dict]) -> str:
    """Simple signal: majority increasing vs decreasing."""
    if not holders:
        return "no_data"
    increases = sum(1 for h in holders if _safe_float(h.get("change") or 0) or 0 > 0)
    decreases = sum(1 for h in holders if _safe_float(h.get("change") or 0) or 0 < 0)
    if increases > decreases:
        return "buy"
    if decreases > increases:
        return "sell"
    return "neutral"


def _safe_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_float_or_none(v) -> float | None:
    """Like _safe_float but also returns None for NaN."""
    import math
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None
