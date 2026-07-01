"""Compute 融資融券背離訊號 (Margin/Short Divergence Signals) for Taiwan stocks.

Signals derived from TWSE MI_MARGN daily margin trading data:

  1. 融資餘額趨勢      margin balance 5-day change %
  2. 融券餘額趨勢      short balance 5-day change %
  3. 券資比            short_balance / margin_balance × 100
  4. 過熱警訊          三條件同時: 股價突破近20日高點 + 融資5日增幅>10% + 法人淨賣超
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from data_sources.tw.db import TaiwanStockDB
from data_sources.tw.margin import fetch_margin_range_for_stock

_DB_PATH = str(Path(__file__).parents[3] / "tw_stock.db")


# ── Data acquisition ──────────────────────────────────────────────────────────

def ensure_margin_data(
    tw_id: str,
    target_days: int = 120,
    force_refresh: bool = False,
    on_progress=None,
) -> Dict[str, Any]:
    """Ensure at least target_days of 融資融券 data exists in DB for tw_id.

    Returns {status, days_available, newly_fetched, message}
    """
    with TaiwanStockDB(_DB_PATH) as db:
        existing_dates = db.get_margin_dates(tw_id, days=target_days + 30)

    already_have = len(existing_dates)
    if already_have >= target_days and not force_refresh:
        return {
            "status":        "ok",
            "days_available": already_have,
            "newly_fetched":  0,
            "message":        "cache_hit",
        }

    need = max(0, target_days - already_have)
    records = fetch_margin_range_for_stock(
        stock_id=tw_id,
        existing_dates=existing_dates,
        target_trading_days=need,
        request_delay=1.0,
        on_progress=on_progress,
    )

    inserted = 0
    with TaiwanStockDB(_DB_PATH) as db:
        for rec in records:
            ok = db.insert_margin_data(
                stock_id=rec["stock_id"],
                date=rec["date"],
                margin_balance=rec["margin_balance"],
                margin_buy=rec["margin_buy"],
                margin_sell=rec["margin_sell"],
                short_balance=rec["short_balance"],
                short_sell=rec["short_sell"],
                short_cover=rec["short_cover"],
            )
            if ok:
                inserted += 1

    return {
        "status":        "ok",
        "days_available": already_have + inserted,
        "newly_fetched":  inserted,
        "message":        "fetched" if inserted else "no_new_data",
    }


# ── Signal computation ────────────────────────────────────────────────────────

def compute_tw_margin_signals(
    tw_id: str, days: int = 60
) -> Dict[str, Any]:
    """Compute 融資融券 divergence signals.

    Reads from DB only (no network calls). Call ensure_margin_data() first.

    Returns dict with available (bool), signals (dict), history (list)
    """
    with TaiwanStockDB(_DB_PATH) as db:
        rows = db.get_margin_data(tw_id, days=days + 10)
        # Also fetch latest institutional flow for the 法人減碼 check
        inst_rows = db.get_institutional_flow_with_prices(tw_id, days=5)

    if not rows:
        return {"available": False, "reason": "no_data", "stock_id": tw_id}

    rows.sort(key=lambda r: r["date"])
    rows = rows[-days:]
    n = len(rows)

    if n < 5:
        return {
            "available": False,
            "reason": "insufficient_data",
            "days_available": n,
            "stock_id": tw_id,
        }

    def _rnd(v: Optional[float], dec: int = 2) -> Optional[float]:
        return round(v, dec) if v is not None else None

    latest = rows[-1]

    # ── No-margin check (ETF, surveillance list, newly listed) ───────────────
    if (latest.get("margin_balance") or 0) == 0 and (latest.get("short_balance") or 0) == 0:
        return {
            "available": False,
            "reason":    "no_margin_trading",
            "stock_id":  tw_id,
        }

    margin_bal  = latest.get("margin_balance") or 0
    short_bal   = latest.get("short_balance")  or 0
    current_price = latest.get("close_price")

    # ── 融資5日增幅 ───────────────────────────────────────────────────────────
    margin_5d_chg_pct: Optional[float] = None
    if n >= 5:
        prev5 = rows[-5].get("margin_balance") or 0
        if prev5 > 0:
            margin_5d_chg_pct = (margin_bal - prev5) / prev5 * 100.0

    # ── 融券5日增幅 ───────────────────────────────────────────────────────────
    short_5d_chg_pct: Optional[float] = None
    if n >= 5:
        prev5_s = rows[-5].get("short_balance") or 0
        if prev5_s > 0:
            short_5d_chg_pct = (short_bal - prev5_s) / prev5_s * 100.0

    # ── 趨勢方向 ─────────────────────────────────────────────────────────────
    def _trend(chg: Optional[float]) -> str:
        if chg is None:
            return "unknown"
        return "up" if chg > 2 else ("down" if chg < -2 else "flat")

    # ── 券資比 ────────────────────────────────────────────────────────────────
    short_margin_ratio: Optional[float] = (
        short_bal / margin_bal * 100.0 if margin_bal > 0 else None
    )

    # ── 近20日股價高點 ────────────────────────────────────────────────────────
    price_20d_rows = [r for r in rows[-20:] if r.get("close_price")]
    price_20d_high: Optional[float] = (
        max(r["close_price"] for r in price_20d_rows) if price_20d_rows else None
    )
    price_at_20d_high = bool(
        current_price and price_20d_high
        and current_price >= price_20d_high * 0.99   # within 1% of the 20d high
    )

    # ── 法人最近是否淨賣超 ────────────────────────────────────────────────────
    institutional_selling: Optional[bool] = None
    if inst_rows:
        inst_rows_sorted = sorted(inst_rows, key=lambda r: r["date"])
        latest_inst = inst_rows_sorted[-1]
        total_net = latest_inst.get("total_net")
        if total_net is not None:
            institutional_selling = total_net < 0

    # ── 股價5日漲跌 ───────────────────────────────────────────────────────────
    price_5d_chg_pct: Optional[float] = None
    if n >= 5 and current_price:
        prev5_p = rows[-5].get("close_price")
        if prev5_p and prev5_p > 0:
            price_5d_chg_pct = (current_price - prev5_p) / prev5_p * 100.0

    # ── 過熱警訊 (三條件同時) ────────────────────────────────────────────────
    divergence_flag = "overheating" if (
        price_at_20d_high
        and (margin_5d_chg_pct or 0) > 10
        and institutional_selling is True
    ) else "normal"

    # ── History for sparkline (last 30 rows) ─────────────────────────────────
    history = [
        {
            "date":           r["date"],
            "margin_balance": r.get("margin_balance"),
            "short_balance":  r.get("short_balance"),
            "close_price":    r.get("close_price"),
        }
        for r in rows[-30:]
    ]

    return {
        "available":  True,
        "stock_id":   tw_id,
        "days_available": n,
        "signals": {
            "margin_balance":        margin_bal,
            "margin_5d_chg_pct":     _rnd(margin_5d_chg_pct, 2),
            "margin_trend":          _trend(margin_5d_chg_pct),
            "short_balance":         short_bal,
            "short_5d_chg_pct":      _rnd(short_5d_chg_pct, 2),
            "short_trend":           _trend(short_5d_chg_pct),
            "short_margin_ratio":    _rnd(short_margin_ratio, 2),
            "price_5d_chg_pct":      _rnd(price_5d_chg_pct, 2),
            "price_at_20d_high":     price_at_20d_high,
            "institutional_selling": institutional_selling,
            "divergence_flag":       divergence_flag,
        },
        "history": history,
    }
