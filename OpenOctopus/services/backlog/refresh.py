"""Backlog refresh service.

Fetches live market data for a list of tickers using yfinance.
Returns price, 52-week high/low, MA10, MA50, vs-52w-low %, and sector info.
"""

from __future__ import annotations

import time
import logging
from datetime import datetime

from services.ashare import is_cn, strip_suffix
from services.ashare.names import get_cn_name_map
from services.screener.ticker_sources import _update_cn_name_cache
from services.tw.names import get_tw_name_map, refresh_tw_name_cache

logger = logging.getLogger(__name__)

_cn_name_map: dict | None = None
_tw_name_map: dict | None = None


def _detect_currency(ticker: str) -> str | None:
    """Return ISO currency code for a ticker, or None for USD/default."""
    t = ticker.upper().strip()
    if is_cn(t):                                      # .SH / .SZ / .BJ
        return "CNY"
    if t.endswith(".TW") or t.endswith(".TWO") or t.isdigit():
        return "TWD"
    return None


def _get_cn_names() -> dict:
    """Lazy-load CN name map once per process (refreshed when screener runs)."""
    global _cn_name_map
    if _cn_name_map is None:
        _cn_name_map = get_cn_name_map()
    return _cn_name_map


def _get_tw_names() -> dict:
    """Lazy-load TW name map once per process (cache TTL 7 days)."""
    global _tw_name_map
    if _tw_name_map is None:
        _tw_name_map = get_tw_name_map()
    return _tw_name_map


def _fetch_one(ticker: str) -> dict:
    """Fetch live data for a single ticker. Returns a dict; sets 'error' on failure.

    Retries once on transient errors (SSL, connection reset, etc.).
    yfinance manages its own curl_cffi session internally.
    """
    import yfinance as yf  # lazy import to keep module load fast
    from services.ashare import to_yf_ticker

    t = ticker.upper()
    yf_sym = to_yf_ticker(t)  # .SH → .SS for Yahoo Finance
    last_exc: Exception | None = None

    for attempt in range(2):
        if attempt > 0:
            time.sleep(1.5)
        try:
            yticker = yf.Ticker(yf_sym)
            info = yticker.info or {}

            # Price fallback chain: regularMarketPrice → currentPrice → previousClose
            price = (
                info.get("regularMarketPrice")
                or info.get("currentPrice")
                or info.get("previousClose")
            )

            w52_high = info.get("fiftyTwoWeekHigh")
            w52_low = info.get("fiftyTwoWeekLow")

            # Compute vs_52w_low: (price - w52_low) / w52_low * 100
            vs_52w_low = None
            if price is not None and w52_low and w52_low > 0:
                vs_52w_low = round((price - w52_low) / w52_low * 100, 1)

            # Compute w52_chg_pct: (w52_high - w52_low) / w52_low * 100
            w52_chg_pct = None
            if w52_high is not None and w52_low and w52_low > 0:
                w52_chg_pct = round((w52_high - w52_low) / w52_low * 100, 1)

            # MA — need 1y of history for MA250
            ma10 = ma20 = ma50 = ma120 = ma250 = None
            dma10 = dma20 = dma120 = dma250 = None
            try:
                hist = yticker.history(period="1y", interval="1d")
                hist = hist[hist["Close"].notna()]
                if not hist.empty and len(hist) >= 10:
                    close = hist["Close"]
                    if price is None and not close.empty:
                        price = float(close.iloc[-1])

                    def _ma(n):
                        if len(close) < n:
                            return None
                        v = close.rolling(n).mean().iloc[-1]
                        return round(float(v), 2) if v == v else None  # NaN guard

                    ma10  = _ma(10)
                    ma20  = _ma(20)
                    ma50  = _ma(50)
                    ma120 = _ma(120)
                    ma250 = _ma(250)

                    if price is not None:
                        def _dma(ma_val):
                            if ma_val is not None and ma_val > 0:
                                return round((price - ma_val) / ma_val * 100, 1)
                            return None
                        dma10  = _dma(ma10)
                        dma20  = _dma(ma20)
                        dma120 = _dma(ma120)
                        dma250 = _dma(ma250)
            except Exception as e:
                logger.warning("backlog: history fetch failed for %s: %s", t, e)

            # Industry sub-category and prosperity indicator (A-shares only)
            industry_sub = None
            sector_pulse = None
            if is_cn(t):
                try:
                    from services.ashare.industry import get_industry
                    from services.ashare.sector_pulse import get_sector_pulse
                    industry_sub = get_industry(t)
                    if industry_sub:
                        sector_pulse = get_sector_pulse(industry_sub)
                except Exception as _e:
                    logger.debug("backlog: industry/pulse fetch failed for %s: %s", t, _e)

            name_cn = _get_cn_names().get(t) if is_cn(t) else None

            # CN: AKShare fallback for manually-added tickers not in screener cache
            if is_cn(t) and name_cn is None:
                try:
                    import akshare as ak
                    code = strip_suffix(t)
                    em_df = ak.stock_individual_info_em(symbol=code)
                    row = em_df[em_df.iloc[:, 0] == '股票简称']
                    if row.empty:
                        row = em_df[em_df.iloc[:, 0] == '股票簡稱']
                    if not row.empty:
                        name_cn = str(row.iloc[0, 1])
                        _update_cn_name_cache({t: name_cn})
                        _cn_name_map[t] = name_cn
                except Exception as _e:
                    logger.debug("backlog: AKShare name fallback failed for %s: %s", t, _e)

            # TW: lookup by 4-digit code; force cache refresh if empty
            if name_cn is None and _detect_currency(t) == "TWD":
                code = t.split(".")[0] if "." in t else t
                tw_map = _get_tw_names()
                if not tw_map:
                    try:
                        tw_map = refresh_tw_name_cache()
                        global _tw_name_map
                        _tw_name_map = tw_map
                    except Exception:
                        pass
                name_cn = tw_map.get(code)
            return {
                "ticker": t,
                "name": info.get("shortName") or info.get("longName") or t,
                "name_cn": name_cn,
                "industry_sub": industry_sub,
                "sector_pulse": sector_pulse,
                "sector": info.get("sector") or "—",
                "currency": _detect_currency(t),
                "price": round(float(price), 2) if price is not None else None,
                "vs_52w_low": vs_52w_low,
                "w52_chg_pct": w52_chg_pct,
                "w52_high": round(float(w52_high), 2) if w52_high is not None else None,
                "w52_low": round(float(w52_low), 2) if w52_low is not None else None,
                "ma10": ma10,
                "ma20": ma20,
                "ma50": ma50,
                "ma120": ma120,
                "ma250": ma250,
                "dma10": dma10,
                "dma20": dma20,
                "dma120": dma120,
                "dma250": dma250,
                "error": None,
                "updated_at": datetime.now().isoformat()[:19],
            }
        except Exception as e:
            last_exc = e
            logger.warning("backlog: _fetch_one attempt %d failed for %s: %s", attempt + 1, t, e)

    return {
        "ticker": t,
        "name": None,
        "name_cn": None,
        "industry_sub": None,
        "sector_pulse": None,
        "sector": None,
        "price": None,
        "vs_52w_low": None,
        "w52_chg_pct": None,
        "w52_high": None,
        "w52_low": None,
        "ma10": None,
        "ma20": None,
        "ma50": None,
        "ma120": None,
        "ma250": None,
        "dma10": None,
        "dma20": None,
        "dma120": None,
        "dma250": None,
        "error": str(last_exc),
        "updated_at": datetime.now().isoformat()[:19],
    }


def fetch_backlog_data(tickers: list[str]) -> list[dict]:
    """Fetch live data for a list of tickers, up to 5 concurrent yfinance calls."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results_map: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_ticker = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(future_to_ticker):
            t = future_to_ticker[future]
            try:
                results_map[t] = future.result()
            except Exception as exc:
                results_map[t] = {
                    "ticker": t.upper(), "name": None, "name_cn": None,
                    "industry_sub": None, "sector_pulse": None, "sector": None,
                    "price": None, "vs_52w_low": None, "w52_chg_pct": None,
                    "w52_high": None, "w52_low": None,
                    "ma10": None, "ma20": None, "ma50": None, "ma120": None, "ma250": None,
                    "dma10": None, "dma20": None, "dma120": None, "dma250": None,
                    "error": str(exc),
                    "updated_at": datetime.now().isoformat()[:19],
                }
    return [results_map.get(t, {"ticker": t.upper(), "error": "not fetched"}) for t in tickers]
