"""
Chip Analysis - Volume Data
Computes RVOL, VWAP estimate, and 20-day volume history from yfinance.
"""
from __future__ import annotations

from datetime import datetime, timezone
import yfinance as yf


def fetch_volume_data(ticker: str) -> dict:
    from services.ashare import to_yf_ticker
    t = ticker.upper()
    yf_sym = to_yf_ticker(t)  # .SH → .SS for Yahoo Finance
    try:
        hist = yf.Ticker(yf_sym).history(period="3mo", interval="1d")
    except Exception as e:
        return {"ticker": t, "error": str(e), "fetched_at": _now()}

    # Drop rows where volume is 0 or close price is missing (intraday partial rows)
    hist = hist[(hist["Volume"] > 0) & hist["Close"].notna()].copy()

    if len(hist) < 2:
        return {"ticker": t, "error": "Insufficient history data", "fetched_at": _now()}

    # Latest day might be partial (intraday); everything before is complete
    latest = hist.iloc[-1]
    prior = hist.iloc[:-1]

    avg_20d_vol = float(prior["Volume"].tail(20).mean()) if len(prior) >= 1 else None
    today_vol = float(latest["Volume"])

    rvol = round(today_vol / avg_20d_vol, 2) if avg_20d_vol and avg_20d_vol > 0 else None

    if rvol is None:
        rvol_signal = "no_data"
    elif rvol >= 2.0:
        rvol_signal = "high"
    elif rvol >= 1.0:
        rvol_signal = "normal"
    else:
        rvol_signal = "low"

    # VWAP estimate: sum((H+L+C)/3 * V) / sum(V) over last 20 complete days
    recent_20 = prior.tail(20)
    typical = (recent_20["High"] + recent_20["Low"] + recent_20["Close"]) / 3
    total_pv = (typical * recent_20["Volume"]).sum()
    total_v = recent_20["Volume"].sum()
    vwap_est = round(float(total_pv / total_v), 2) if total_v > 0 else None

    latest_close = round(float(latest["Close"]), 2)
    price_vs_vwap_pct = (
        round((latest_close - vwap_est) / vwap_est * 100, 2)
        if vwap_est and vwap_est > 0
        else None
    )

    # Build 20-day volume history for chart
    chart_data = prior.tail(20)
    vol_avg = float(chart_data["Volume"].mean()) if len(chart_data) > 0 else 0
    volume_history = [
        {
            "date": str(idx.date()) if hasattr(idx, "date") else str(idx)[:10],
            "volume": int(row["Volume"]),
            "avg_volume": int(vol_avg),
        }
        for idx, row in chart_data.iterrows()
    ]
    # Append today
    volume_history.append(
        {
            "date": str(latest.name.date()) if hasattr(latest.name, "date") else str(latest.name)[:10],
            "volume": int(today_vol),
            "avg_volume": int(avg_20d_vol) if avg_20d_vol else 0,
            "is_today": True,
        }
    )

    # Detect partial day: if current time is between 9:30-16:00 ET weekday
    now_utc = datetime.now(timezone.utc)
    is_partial_day = _is_market_hours(now_utc)

    return {
        "ticker": t,
        "rvol": rvol,
        "rvol_signal": rvol_signal,
        "today_volume": int(today_vol),
        "avg_20d_volume": int(avg_20d_vol) if avg_20d_vol else None,
        "vwap_est": vwap_est,
        "latest_close": latest_close,
        "price_vs_vwap_pct": price_vs_vwap_pct,
        "volume_history": volume_history,
        "is_partial_day": is_partial_day,
        "fetched_at": _now(),
        "error": None,
    }


def _is_market_hours(now_utc: datetime) -> bool:
    """Rough check: NYSE trading hours 9:30-16:00 ET = 13:30-20:00 UTC (EST, no DST adjust)."""
    if now_utc.weekday() >= 5:
        return False
    h = now_utc.hour + now_utc.minute / 60
    return 13.5 <= h <= 20.0


def _now() -> str:
    return datetime.now().isoformat()[:19]
