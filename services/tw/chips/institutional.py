"""Compute 籌碼訊號矩陣 (Sentiment Signal Matrix) for Taiwan stocks.

Eight indicators derived from TWSE 三大法人 daily flow data:

  1. 連續買超/賣超天數 (Consecutive Momentum)
     consecutive_days × net_buy / volume = 籌碼凝聚力 (cohesion index)

  2. 法人持股比率變化 ROC  (Institutional Ownership Rate of Change)
     Accumulated net flow / shares_outstanding → derive recent vs older half ROC

  3. 投信佈局率  (Domestic Fund Layout Rate)
     Σ fund_net / Σ volume over window

  4. 成本乖離率  (Cost Deviation from Institutional Cost Basis)
     Σ(net_buy × close) / Σ(net_buy) = weighted avg cost;
     deviation = (current_price - cost) / cost

  5. 籌碼集中度  (Chips Concentration)
     Σ total_net / Σ volume over 20-day rolling window

  6. 法人一致性  (Institutional Consensus)
     How many of {foreign, fund, dealer} are net-buying same day (0–3 score);
     triple-buy streak and fund-only streak

  7. 多週期成本線  (Multi-period Cost Lines)
     Weighted avg cost over 20 / 60 / 120-day windows; deviation from current price

  8. 佔成交量比重  (Volume Dominance)
     abs(total_net) / volume_shares for latest day; flag if ≥ 20%
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional

import yfinance as yf

from data_sources.tw.db import TaiwanStockDB
from data_sources.tw.institutional import fetch_range_for_stock

_DB_PATH = str(Path(__file__).parents[3] / "tw_stock.db")

# Signal threshold: consecutive days that constitute a meaningful signal
_CONSECUTIVE_THRESHOLD = 5
# Concentration window (trading days)
_CONCENTRATION_WINDOW = 20


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_shares_outstanding(tw_id: str) -> Optional[int]:
    """Shares outstanding from yfinance fast_info."""
    try:
        fi = yf.Ticker(f"{tw_id}.TW").fast_info
        val = fi.get("shares") or fi.get("sharesOutstanding")
        return int(val) if val else None
    except Exception:
        return None


def _ensure_price_data(tw_id: str, days: int = 80) -> None:
    """Ensure yfinance price history is in daily_prices for this stock."""
    try:
        import pandas as pd
        ticker = yf.Ticker(f"{tw_id}.TW")
        hist = ticker.history(period=f"{days}d")
        if hist.empty:
            return
        with TaiwanStockDB(_DB_PATH) as db:
            hist_reset = hist.reset_index()
            hist_reset['Date'] = pd.to_datetime(hist_reset['Date']).dt.strftime('%Y-%m-%d')
            hist_reset.rename(columns={'Date': 'date', 'Open': 'open', 'High': 'high',
                                       'Low': 'low', 'Close': 'close',
                                       'Volume': 'volume'}, inplace=True)
            hist_reset['stock_id'] = tw_id
            hist_reset['adj_close'] = hist_reset['close']
            for _, row in hist_reset.iterrows():
                try:
                    db.conn.execute(
                        'INSERT OR IGNORE INTO daily_prices '
                        '(stock_id, date, open, high, low, close, adj_close, volume) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                        (tw_id, row['date'], row.get('open'), row.get('high'),
                         row.get('low'), row.get('close'), row.get('close'), row.get('volume'))
                    )
                except Exception:
                    pass
            db.conn.commit()
    except Exception:
        pass


# ── Data acquisition ──────────────────────────────────────────────────────────

def ensure_institutional_data(
    tw_id: str,
    target_days: int = 120,
    force_refresh: bool = False,
    on_progress=None,
) -> Dict[str, Any]:
    """Ensure at least target_days of 三大法人 data exists in DB for tw_id.

    Returns {status, days_available, newly_fetched, message}
    """
    with TaiwanStockDB(_DB_PATH) as db:
        existing_dates = db.get_institutional_flow_dates(tw_id, days=target_days + 30)

    already_have = len(existing_dates)
    if already_have >= target_days and not force_refresh:
        return {
            "status": "ok",
            "days_available": already_have,
            "newly_fetched": 0,
            "message": "cache_hit",
        }

    # Ensure we also have price data for the cost-basis calculation
    _ensure_price_data(tw_id, days=target_days + 20)

    need = max(0, target_days - already_have)
    records = fetch_range_for_stock(
        stock_id=tw_id,
        existing_dates=existing_dates,
        target_trading_days=need,
        request_delay=1.0,
        on_progress=on_progress,
    )

    inserted = 0
    with TaiwanStockDB(_DB_PATH) as db:
        for rec in records:
            ok = db.insert_institutional_flow(
                stock_id=rec["stock_id"],
                date=rec["date"],
                foreign_net=rec["foreign_net"],
                fund_net=rec["fund_net"],
                dealer_net=rec["dealer_net"],
                total_net=rec["total_net"],
            )
            if ok:
                inserted += 1

    return {
        "status": "ok",
        "days_available": already_have + inserted,
        "newly_fetched": inserted,
        "message": "fetched" if inserted else "no_new_data",
    }


# ── Signal computation ────────────────────────────────────────────────────────

def compute_tw_chips_signals(
    tw_id: str, days: int = 120
) -> Dict[str, Any]:
    """Compute all eight 籌碼訊號矩陣 indicators.

    Reads from DB only (no network calls).  Call ensure_institutional_data()
    first to guarantee fresh data is available.

    Returns dict with:
        available (bool), days_available (int), signals (dict), history (list)
    """
    with TaiwanStockDB(_DB_PATH) as db:
        rows = db.get_institutional_flow_with_prices(tw_id, days=days + 10)

    if not rows:
        return {"available": False, "reason": "no_data", "stock_id": tw_id}

    # Sort oldest → newest, keep at most `days` rows
    rows.sort(key=lambda r: r["date"])
    rows = rows[-days:]
    n = len(rows)

    if n < 3:
        return {
            "available": False,
            "reason": "insufficient_data",
            "days_available": n,
            "stock_id": tw_id,
        }

    def _rnd(v: Optional[float], dec: int = 2) -> Optional[float]:
        return round(v, dec) if v is not None else None

    # ── 1. 連續買超/賣超天數 ──────────────────────────────────────────────────
    latest_net = rows[-1]["total_net"] or 0
    if latest_net > 0:
        direction = "buy"
        streak = 0
        for r in reversed(rows):
            if (r["total_net"] or 0) > 0:
                streak += 1
            else:
                break
    elif latest_net < 0:
        direction = "sell"
        streak = 0
        for r in reversed(rows):
            if (r["total_net"] or 0) < 0:
                streak += 1
            else:
                break
    else:
        direction = "neutral"
        streak = 0

    streak_rows = rows[-streak:] if streak > 0 else []
    streak_vol = sum((r["volume_shares"] or 0) for r in streak_rows)
    streak_net = sum(abs(r["total_net"] or 0) for r in streak_rows)
    cohesion = (streak * streak_net / streak_vol * 100.0) if streak_vol > 0 else 0.0

    # ── 2. 法人持股比率 ROC ───────────────────────────────────────────────────
    shares_out = _get_shares_outstanding(tw_id) or 1
    half = n // 2
    net_recent = sum(r["total_net"] or 0 for r in rows[half:])
    net_older  = sum(r["total_net"] or 0 for r in rows[:half])

    ownership_change_pct = (net_recent + net_older) / shares_out * 100.0

    rate_older  = net_older  / shares_out * 100.0
    rate_recent = net_recent / shares_out * 100.0
    if abs(rate_older) > 1e-9:
        roc_pct = (rate_recent - rate_older) / abs(rate_older) * 100.0
    else:
        roc_pct = 100.0 if rate_recent > 0 else (-100.0 if rate_recent < 0 else 0.0)
    ownership_trend = "up" if roc_pct > 10 else ("down" if roc_pct < -10 else "flat")

    # ── 3. 投信佈局率 ─────────────────────────────────────────────────────────
    total_vol    = sum(r["volume_shares"] or 0 for r in rows)
    fund_net_sum = sum(r["fund_net"] or 0 for r in rows)
    fund_layout_rate = (fund_net_sum / total_vol * 100.0) if total_vol > 0 else 0.0
    fund_signal = (
        "high"   if fund_layout_rate >  1.0 else
        "medium" if fund_layout_rate >  0.3 else
        "low"
    )

    # ── 4. 成本乖離率 ─────────────────────────────────────────────────────────
    buy_rows = [
        r for r in rows
        if (r["total_net"] or 0) > 0 and r["close_price"]
    ]
    total_buy = sum(r["total_net"] for r in buy_rows)
    if total_buy > 0:
        weighted_cost: Optional[float] = (
            sum(r["total_net"] * r["close_price"] for r in buy_rows) / total_buy
        )
    else:
        weighted_cost = None

    current_price = rows[-1].get("close_price") if rows else None
    if current_price and weighted_cost and weighted_cost > 0:
        deviation_pct: Optional[float] = (current_price - weighted_cost) / weighted_cost * 100.0
    else:
        deviation_pct = None

    # ── 5. 籌碼集中度 ─────────────────────────────────────────────────────────
    win_rows = rows[-_CONCENTRATION_WINDOW:]
    win_net  = sum(r["total_net"] or 0 for r in win_rows)
    win_vol  = sum(r["volume_shares"] or 0 for r in win_rows)
    concentration_pct = (win_net / win_vol * 100.0) if win_vol > 0 else 0.0

    # ── 6. 法人一致性 ─────────────────────────────────────────────────────────
    def _cscore(r: dict) -> int:
        return sum(1 for v in [r.get("foreign_net"), r.get("fund_net"), r.get("dealer_net")]
                   if (v or 0) > 0)

    # Triple herd streak: consecutive days all 3 institutions net-buying
    triple_streak = 0
    for r in reversed(rows):
        if ((r.get("foreign_net") or 0) > 0
                and (r.get("fund_net") or 0) > 0
                and (r.get("dealer_net") or 0) > 0):
            triple_streak += 1
        else:
            break

    # Fund-only consecutive streak (投信獨立連買)
    fund_streak = 0
    for r in reversed(rows):
        if (r.get("fund_net") or 0) > 0:
            fund_streak += 1
        else:
            break

    latest_consensus = _cscore(rows[-1])
    recent20 = rows[-20:]
    avg_consensus_20d = (
        sum(_cscore(r) for r in recent20) / len(recent20)
        if recent20 else 0.0
    )

    # ── 7. 多週期成本線 ────────────────────────────────────────────────────────
    def _compute_cost(rows_slice: list) -> Optional[float]:
        b = [r for r in rows_slice if (r.get("total_net") or 0) > 0 and r.get("close_price")]
        tb = sum(r["total_net"] for r in b)
        return sum(r["total_net"] * r["close_price"] for r in b) / tb if tb > 0 else None

    def _dev(cost: Optional[float]) -> Optional[float]:
        if cost and current_price and cost > 0:
            return (current_price - cost) / cost * 100.0
        return None

    cost_20d  = _compute_cost(rows[-20:])  if n >= 20  else None
    cost_60d  = _compute_cost(rows[-60:])  if n >= 60  else None
    cost_120d = _compute_cost(rows[-120:]) if n >= 120 else None

    # ── 8. 佔成交量比重 ────────────────────────────────────────────────────────
    latest_total_net = rows[-1].get("total_net") or 0
    latest_vol_day   = rows[-1].get("volume_shares") or 0
    vol_dominance_pct = (
        abs(latest_total_net) / latest_vol_day * 100.0
        if latest_vol_day > 0 else 0.0
    )

    # ── History for sparklines (last 30 rows) ────────────────────────────────
    history = [
        {
            "date":        r["date"],
            "total_net":   r["total_net"],
            "foreign_net": r["foreign_net"],
            "fund_net":    r["fund_net"],
            "dealer_net":  r["dealer_net"],
            "close_price": r["close_price"],
            "consensus":   _cscore(r),
        }
        for r in rows[-30:]
    ]

    return {
        "available":    True,
        "days_available": n,
        "stock_id":     tw_id,
        "signals": {
            "consecutive": {
                "days":       streak,
                "direction":  direction,
                "cohesion":   _rnd(cohesion, 4),
                "threshold":  _CONSECUTIVE_THRESHOLD,
                "is_signal":  streak >= _CONSECUTIVE_THRESHOLD,
            },
            "ownership_roc": {
                "ownership_change_pct": _rnd(ownership_change_pct, 4),
                "roc_pct":   _rnd(roc_pct, 2),
                "trend":     ownership_trend,
            },
            "fund_layout": {
                "layout_rate_pct": _rnd(fund_layout_rate, 4),
                "signal":          fund_signal,
            },
            "cost_deviation": {
                "institutional_cost": _rnd(weighted_cost, 2),
                "current_price":      _rnd(current_price, 2),
                "deviation_pct":      _rnd(deviation_pct, 2),
            },
            "concentration": {
                "concentration_pct":  _rnd(concentration_pct, 4),
                "window_days":        len(win_rows),
                "direction":          "buy" if win_net > 0 else ("sell" if win_net < 0 else "neutral"),
                "vol_dominance_pct":  _rnd(vol_dominance_pct, 2),
                "is_dominant":        vol_dominance_pct >= 20.0,
            },
            "consensus": {
                "latest_score":      latest_consensus,
                "triple_streak":     triple_streak,
                "fund_streak":       fund_streak,
                "avg_consensus_20d": _rnd(avg_consensus_20d, 2),
            },
            "multi_cost": {
                "current_price":  _rnd(current_price, 2),
                "cost_20d":       _rnd(cost_20d, 2),
                "dev_20d_pct":    _rnd(_dev(cost_20d), 2),
                "cost_60d":       _rnd(cost_60d, 2),
                "dev_60d_pct":    _rnd(_dev(cost_60d), 2),
                "cost_120d":      _rnd(cost_120d, 2),
                "dev_120d_pct":   _rnd(_dev(cost_120d), 2),
            },
        },
        "history": history,
    }
