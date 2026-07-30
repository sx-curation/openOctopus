"""Northbound capital (北向资金) per-stock holdings.

Uses AKShare stock_hsgt_individual_em (沪深港通个股资金流向).
Data is T+1 delayed — always annotate data_date in the response.
"""
from __future__ import annotations

import logging

from services.ashare import strip_suffix

logger = logging.getLogger(__name__)


def fetch_northbound(ticker: str) -> dict:
    """Return northbound capital holding data for ticker.

    Response schema:
        hold_shares:          total northbound holdings (shares)
        hold_ratio_pct:       holding as % of float shares
        daily_change_shares:  net change on the latest data date
        available:            bool
        data_date:            ISO date string (T+1)
    """
    import akshare as ak

    code = strip_suffix(ticker)
    try:
        df = ak.stock_hsgt_individual_em(symbol=code)
        if df is None or df.empty:
            return {"available": False}
        latest = df.iloc[-1]
        # Verified column layout for stock_hsgt_individual_em:
        # 0=日期, 1=收盘价, 2=涨跌幅, 3=持股数量(shares), 4=持股市值,
        # 5=持股占A股比例(%), 6=当日持股变化(shares), 7=当日成交变化, 8=近日市值变化
        return {
            "hold_shares":         _safe_float(latest.iloc[3]),
            "hold_ratio_pct":      _safe_float(latest.iloc[5]),
            "daily_change_shares": _safe_float(latest.iloc[6]) if len(latest) > 6 else None,
            "available":           True,
            "data_date":           str(latest.iloc[0])[:10],  # ⚠️ T+1 delayed
        }
    except Exception as e:
        logger.debug("northbound.fetch_northbound: %s: %s", ticker, e)
        return {"available": False}


def _safe_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
