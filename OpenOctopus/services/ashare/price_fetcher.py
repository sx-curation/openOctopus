"""A-share price fetchers: Tencent Finance (primary) + TDX (fallback)."""
from __future__ import annotations

import time

import pandas as pd
import requests

from . import market_id, strip_suffix


def fetch_prices_tencent(ticker: str, count: int = 320) -> pd.Series | None:
    """Fetch daily close prices from Tencent Finance (qfq adjusted).

    URL path: data[prefix+code]["day"] -> list of [date, open, close, high, low, vol]
    Note: index 2 = close (NOT last column).
    """
    prefix = "sh" if ticker.upper().endswith(".SH") else "sz"
    code = strip_suffix(ticker)
    url = (
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={prefix}{code},day,,,{count},qfq"
    )
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.json()
        key = prefix + code
        stock_data = (data.get("data") or {}).get(key, {})
        # qfq-adjusted key is "qfqday"; non-adjusted is "day"
        bars = stock_data.get("qfqday") or stock_data.get("day") or []
        if not bars:
            return None
        dates = pd.to_datetime([b[0] for b in bars])
        closes = [float(b[2]) for b in bars]
        s = pd.Series(closes, index=dates, name=ticker)
        s = s[~s.index.duplicated(keep="last")].sort_index()
        time.sleep(0.12)
        return s if len(s) >= 10 else None
    except Exception:
        return None


def fetch_prices_tdx(ticker: str, count: int = 320) -> pd.Series | None:
    """Fetch daily close prices via pytdx. Falls back silently on timeout."""
    try:
        from .tdx_client import get_api, reset_api
        code = strip_suffix(ticker)
        mkt = market_id(ticker)
        api = get_api()
        bars = api.get_security_bars(9, mkt, code, 0, count)  # 9=daily
    except Exception:
        try:
            from .tdx_client import reset_api
            reset_api()
        except Exception:
            pass
        return None
    if not bars:
        return None
    try:
        df = pd.DataFrame(bars)
        df["date"] = pd.to_datetime(df["datetime"]).dt.normalize()
        df = df.sort_values("date").set_index("date")
        s = df["close"].astype(float).rename(ticker)
        return s if len(s) >= 10 else None
    except Exception:
        return None
