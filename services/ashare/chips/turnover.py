"""Turnover rate (换手率) for A-shares.

Primary: AKShare stock_zh_a_hist_tx (Tencent backend) → 5-day avg volume.
Fallback: direct Tencent Finance HTTP.

换手率 is not available without float-share data.
We return avg_volume_5d and set turnover_rate_pct=null when float shares
are unavailable (all East-Money endpoints are currently unreachable).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import requests

from services.ashare import strip_suffix

logger = logging.getLogger(__name__)

_TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def _exchange_prefix(ticker: str) -> str:
    return "sh" if ticker.upper().endswith(".SH") else "sz"


def _try_akshare_tx(code: str, ticker: str) -> dict | None:
    """Fetch ~22-day history via stock_zh_a_hist_tx (Tencent backend)."""
    import akshare as ak

    symbol = _exchange_prefix(ticker) + code  # e.g. "sz002384"
    end    = date.today()
    start  = end - timedelta(days=35)  # ~22 trading days within 35 calendar days
    try:
        df = ak.stock_zh_a_hist_tx(
            symbol=symbol,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
        )
    except Exception as e:
        logger.debug("turnover._try_akshare_tx: %s: %s", ticker, e)
        return None

    if df is None or df.empty:
        return None

    # Columns: date open close high low amount (amount in 手 = 100 shares)
    recent = df.tail(22)
    try:
        avg_vol      = float(recent["amount"].mean()) * 100  # convert 手 → shares
        prev_day_vol = round(float(recent.iloc[-1]["amount"]))        # 手
        vol_3d_avg   = round(float(recent.tail(3)["amount"].mean()))  # 手

        vol_history: list[dict] = []
        for idx, row in recent.iterrows():
            try:
                d_val = row.get("date", idx) if hasattr(row, "get") else idx
                if hasattr(d_val, "strftime"):
                    d_str = d_val.strftime("%Y-%m-%d")
                else:
                    d_str = str(d_val)[:10]
                vol_history.append({"date": d_str, "vol": round(float(row["amount"]))})
            except Exception:
                pass
    except Exception:
        return None

    return {
        "available":         True,
        "turnover_rate_pct": None,   # float shares not available
        "avg_volume_5d":     round(avg_vol),
        "prev_day_vol":      prev_day_vol,
        "vol_3d_avg":        vol_3d_avg,
        "vol_history":       vol_history,
        "data_source":       "tencent_hist",
    }


def _try_tencent_direct(code: str, ticker: str) -> dict | None:
    """Fetch 5-day volume from Tencent Finance direct HTTP."""
    prefix = _exchange_prefix(ticker)
    params = {"param": f"{prefix}{code},day,,,5,qfq"}
    try:
        resp = requests.get(_TENCENT_URL, params=params, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        # Key may be 'day' or 'qfqday' depending on adjust
        stock_data = data.get("data", {}).get(f"{prefix}{code}", {})
        day_list = stock_data.get("qfqday") or stock_data.get("day") or []
        if not day_list:
            return None
        vols      = []  # shares
        vols_shou = []  # 手 (raw)
        for bar in day_list:
            try:
                raw = float(bar[5])  # index 5 = vol in 手
                vols.append(raw * 100)
                vols_shou.append(raw)
            except (IndexError, TypeError, ValueError):
                pass
        if not vols:
            return None
        return {
            "available":         True,
            "turnover_rate_pct": None,
            "avg_volume_5d":     round(sum(vols) / len(vols)),
            "prev_day_vol":      round(vols_shou[-1]) if vols_shou else None,
            "vol_3d_avg":        round(sum(vols_shou[-3:]) / min(3, len(vols_shou))) if vols_shou else None,
            "vol_history":       [],
            "data_source":       "tencent_direct",
        }
    except Exception as e:
        logger.debug("turnover._try_tencent_direct: %s: %s", ticker, e)
        return None


def fetch_turnover(ticker: str) -> dict:
    """Return turnover rate and average volume for ticker."""
    code = strip_suffix(ticker)

    result = _try_akshare_tx(code, ticker)
    if result:
        return result

    result = _try_tencent_direct(code, ticker)
    if result:
        return result

    return {
        "available":         False,
        "turnover_rate_pct": None,
        "avg_volume_5d":     None,
        "prev_day_vol":      None,
        "vol_3d_avg":        None,
        "vol_history":       [],
        "data_source":       "none",
    }
