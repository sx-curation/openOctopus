"""
services/screener/price_fetcher.py
===================================
Standalone price-data module for the upward-ticker screener.
Intentionally separate from tools/price_data.py so screener logic
can evolve independently.

Public API
----------
  RateLimitError                    – raised on HTTP 429/403
  _to_stooq_ticker(t, market)       – stooq symbol
  _to_yahoo_ticker(t, market)       – yfinance symbol
  _to_fmp_ticker(t, market)         – FMP symbol
  _PDR_AVAILABLE                    – bool
  fetch_prices(ticker, market, priority, min_points) -> (Series|None, src, rl_src)
  compute_metrics(series)           -> dict
  check_conditions(metrics)         -> dict  (c1..c7, selected)
"""
from __future__ import annotations

import os
import random
import time
from typing import Any

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Optional pandas_datareader (stooq) – graceful degradation
# ---------------------------------------------------------------------------
try:
    from pandas_datareader import data as _pdr  # noqa: F401
    _PDR_AVAILABLE = True
except ImportError:
    _pdr = None  # type: ignore[assignment]
    _PDR_AVAILABLE = False

# Optional yfinance
try:
    import yfinance as _yf
    _YF_AVAILABLE = True
except ImportError:
    _yf = None  # type: ignore[assignment]
    _YF_AVAILABLE = False

FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip()
_REQUEST_TIMEOUT = 20
_RETRY = 2
_SLEEP_BETWEEN_RETRIES = (1.0, 2.0)
_TIMESERIES_FMP = 900  # ≈ 900 trading-day window (>= 200 MA + 1yr + buffer)

# ---------------------------------------------------------------------------
# D-1: Custom exception
# ---------------------------------------------------------------------------
class RateLimitError(Exception):
    """Raised when a price source returns HTTP 429 or 403 (rate-limited)."""

    def __init__(self, source: str) -> None:
        super().__init__(f"Rate-limited by source: {source}")
        self.source = source


# ---------------------------------------------------------------------------
# Market identifiers
# ---------------------------------------------------------------------------
MARKET_SP500 = "SP500"
MARKET_NDX = "NASDAQ100"
MARKET_DAX = "DAX40"
MARKET_TW50 = "TW50"

_US_MARKETS = (MARKET_SP500, MARKET_NDX)


# ---------------------------------------------------------------------------
# D-2: Ticker format conversions
# ---------------------------------------------------------------------------

def _to_stooq_ticker(ticker: str, market: str) -> str:
    """Convert canonical ticker to stooq format.

    US (SP500/NASDAQ100): replace dots with hyphens, append .US.
      BRK.B → BRK-B.US  |  META → META.US
    DAX40: append .DE if no dot present.
      SAP → SAP.DE  |  SAP.DE → SAP.DE
    """
    t = (ticker or "").strip().upper()
    if market in _US_MARKETS:
        if t.endswith(".US"):
            return t
        base = t.replace(".", "-")
        return f"{base}.US"
    # DAX40
    if "." not in t:
        return f"{t}.DE"
    return t


def _to_yahoo_ticker(ticker: str, market: str) -> str:
    """Convert canonical ticker to Yahoo Finance / yfinance format.

    US: replace dots with hyphens.
      BRK.B → BRK-B  |  META → META
    DAX40: ensure .DE suffix.
      SAP → SAP.DE  |  SAP.DE → SAP.DE
    TW50: already NNNN.TW, return as-is.
      2330.TW → 2330.TW
    """
    t = (ticker or "").strip().upper()
    if market in _US_MARKETS:
        return t.replace(".", "-")
    if market == MARKET_TW50:
        return t  # already NNNN.TW format
    if t.endswith(".DE"):
        return t
    base = t.split(".")[0]
    return f"{base}.DE"


def _to_fmp_ticker(ticker: str, market: str) -> str:  # noqa: ARG001
    """FMP accepts canonical tickers as-is."""
    return (ticker or "").strip().upper()


# ---------------------------------------------------------------------------
# D-3: Per-source fetch implementations
# ---------------------------------------------------------------------------

def _check_rate_limit(exc: Exception, source: str) -> None:
    """Raise RateLimitError if the exception looks like a 429/403."""
    msg = str(exc).lower()
    if "429" in msg or "403" in msg or "too many" in msg or "rate limit" in msg.replace(" ", ""):
        raise RateLimitError(source) from exc


def fetch_prices_stooq(ticker: str, market: str) -> pd.Series | None:
    """Fetch close prices via pandas_datareader stooq."""
    if not _PDR_AVAILABLE:
        raise RuntimeError("pandas_datareader not installed; stooq unavailable")
    sym = _to_stooq_ticker(ticker, market)
    try:
        df = _pdr.DataReader(sym, "stooq")
    except Exception as exc:
        _check_rate_limit(exc, "stooq")
        raise
    if df is None or df.empty:
        return None
    s: pd.Series = df["Close"].dropna()
    if len(s) < 10:
        return None
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.name = ticker
    return s


def fetch_prices_yahoo(ticker: str, market: str) -> pd.Series | None:
    """Fetch close prices via yfinance."""
    if not _YF_AVAILABLE:
        raise RuntimeError("yfinance not installed; yahoo unavailable")
    sym = _to_yahoo_ticker(ticker, market)
    try:
        df = _yf.download(sym, period="max", auto_adjust=True, progress=False, threads=False)
    except Exception as exc:
        _check_rate_limit(exc, "yahoo")
        raise
    if df is None or df.empty:
        return None
    # yfinance may return MultiIndex on single ticker in some versions
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(level=1, axis=1)
    s: pd.Series = df["Close"].dropna()
    if len(s) < 10:
        return None
    s.index = pd.to_datetime(s.index)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.name = ticker
    return s


def fetch_prices_fmp(ticker: str, market: str) -> pd.Series | None:
    """Fetch close prices via FMP historical API."""
    if not FMP_API_KEY:
        raise RuntimeError("FMP_API_KEY not set; fmp unavailable")
    sym = _to_fmp_ticker(ticker, market)
    url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{sym}"
    try:
        r = requests.get(
            url,
            params={"timeseries": _TIMESERIES_FMP, "apikey": FMP_API_KEY},
            timeout=_REQUEST_TIMEOUT,
        )
        if r.status_code in (429, 403):
            raise RateLimitError("fmp")
        r.raise_for_status()
    except RateLimitError:
        raise
    except Exception as exc:
        _check_rate_limit(exc, "fmp")
        raise
    hist = r.json().get("historical") or []
    if not hist:
        return None
    rows = []
    for item in hist:
        d = item.get("date")
        px = item.get("adjClose")
        if d and px is not None:
            rows.append((pd.to_datetime(d), float(px)))
    if not rows:
        return None
    rows.sort(key=lambda x: x[0])
    s = pd.Series([x[1] for x in rows], index=[x[0] for x in rows], name=ticker).dropna()
    return s if len(s) >= 10 else None


def fetch_prices_twse(ticker: str, market: str) -> pd.Series | None:  # noqa: ARG001
    """Fetch historical close prices from TWSE STOCK_DAY endpoint (Taiwan stocks only).

    Makes up to 12 monthly requests to build ~240 trading days of history.
    Parses Republic-of-China calendar dates (e.g. "113/01/02" → 2024-01-02).
    """
    import re as _re
    stock_no = (ticker or "").strip().upper().replace(".TW", "")
    if not _re.match(r"^\d{4,6}$", stock_no):
        return None

    from datetime import date as _date, timedelta as _timedelta
    _CHROME_HDR = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    rows: list[tuple[pd.Timestamp, float]] = []
    today = _date.today()

    for months_back in range(12):
        # Compute target month start
        d = today.replace(day=1)
        for _ in range(months_back):
            d = (d - _timedelta(days=1)).replace(day=1)

        date_str = d.strftime("%Y%m01")
        url = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
        try:
            r = requests.get(
                url,
                params={"response": "json", "date": date_str, "stockNo": stock_no},
                headers=_CHROME_HDR,
                timeout=_REQUEST_TIMEOUT,
            )
            if r.status_code in (429, 403):
                raise RateLimitError("twse")
            r.raise_for_status()
            payload = r.json()
        except RateLimitError:
            raise
        except Exception:  # noqa: BLE001
            time.sleep(random.uniform(0.5, 1.0))
            continue

        if payload.get("stat") != "OK":
            time.sleep(random.uniform(0.5, 1.0))
            continue

        fields = payload.get("fields") or []
        # "收盤價" is typically index 6; fall back to searching the list
        try:
            close_idx = fields.index("收盤價")
        except ValueError:
            close_idx = 6

        for rec in payload.get("data") or []:
            try:
                date_parts = str(rec[0]).strip().split("/")
                year = int(date_parts[0]) + 1911
                month = int(date_parts[1])
                day = int(date_parts[2])
                close_str = str(rec[close_idx]).replace(",", "").strip()
                close = float(close_str)
                rows.append((pd.Timestamp(year, month, day), close))
            except (ValueError, IndexError, TypeError):
                continue

        time.sleep(random.uniform(0.5, 1.0))

    if not rows:
        return None
    rows.sort(key=lambda x: x[0])
    idx = pd.DatetimeIndex([x[0] for x in rows])
    vals = [x[1] for x in rows]
    s = pd.Series(vals, index=idx, name=ticker).dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s if len(s) >= 10 else None


_SOURCE_FUNCS = {}
if _PDR_AVAILABLE:
    _SOURCE_FUNCS["stooq"] = fetch_prices_stooq
if _YF_AVAILABLE:
    _SOURCE_FUNCS["yahoo"] = fetch_prices_yahoo
_SOURCE_FUNCS["fmp"] = fetch_prices_fmp      # always registered; runtime checks API key
_SOURCE_FUNCS["twse"] = fetch_prices_twse    # always registered; no API key required


# ---------------------------------------------------------------------------
# D-4: Main price-fetch entry point
# ---------------------------------------------------------------------------

def _try_fetch_with_retry(
    func: Any,
    ticker: str,
    market: str,
) -> pd.Series | None:
    """Call *func(ticker, market)* with up to _RETRY retries. Propagates RateLimitError."""
    last_err: Exception | None = None
    for attempt in range(_RETRY + 1):
        try:
            return func(ticker, market)
        except RateLimitError:
            raise  # immediately bubble up; caller handles source switching
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < _RETRY:
                time.sleep(random.uniform(*_SLEEP_BETWEEN_RETRIES))
    raise last_err  # type: ignore[misc]


def fetch_prices(
    ticker: str,
    market: str,
    priority: list[str],
    min_points: int = 260,
) -> tuple[pd.Series | None, str | None, str | None]:
    """Fetch price series, trying sources in *priority* order.

    Returns (series, source_used, rate_limited_source):
      - series: best pd.Series found (may be None if all fail)
      - source_used: name of the source that provided *series*
      - rate_limited_source: last source that returned 429/403 (or None)
    """
    best_s: pd.Series | None = None
    best_src: str | None = None
    last_rl: str | None = None
    remaining = [s for s in priority if s in _SOURCE_FUNCS]

    while remaining:
        src = remaining.pop(0)
        func = _SOURCE_FUNCS[src]
        try:
            s = _try_fetch_with_retry(func, ticker, market)
            if s is not None and len(s) > len(best_s or []):
                best_s = s
                best_src = src
            if best_s is not None and len(best_s) >= min_points:
                return best_s, best_src, last_rl
        except RateLimitError as exc:
            last_rl = exc.source
        except Exception:  # noqa: BLE001
            pass  # source failed, try next

    return best_s, best_src, last_rl


# ---------------------------------------------------------------------------
# D-5: Metrics computation
# ---------------------------------------------------------------------------

def compute_metrics(price: pd.Series) -> dict[str, Any]:
    """Compute MA and range metrics from a price series.

    All values are NaN-safe; insufficient history yields NaN (not an error).
    """
    if isinstance(price, pd.DataFrame):
        price = price.iloc[:, 0]
    s = price.dropna().sort_index()

    def _safe(series: pd.Series, idx: int) -> float:
        try:
            v = series.iloc[idx]
            return float(v) if pd.notna(v) else float("nan")
        except (IndexError, TypeError):
            return float("nan")

    ma200 = s.rolling(200).mean()
    ma150 = s.rolling(150).mean()
    ma50  = s.rolling(50).mean()

    last_price = _safe(s, -1)
    data_start = str(s.index[0].date()) if len(s) else ""
    data_end   = str(s.index[-1].date()) if len(s) else ""

    # 52-week range (252 trading days; fall back to all available data)
    window_252 = s.iloc[-252:] if len(s) >= 30 else s
    w52_low  = float(window_252.min()) if len(window_252) else float("nan")
    w52_high = float(window_252.max()) if len(window_252) else float("nan")

    return {
        "price":        last_price,
        "data_start":   data_start,
        "data_end":     data_end,
        "ma200":        _safe(ma200, -1),
        "ma150":        _safe(ma150, -1),
        "ma50":         _safe(ma50, -1),
        "ma200_1mago":  _safe(ma200, -30),
        "w52_low":      w52_low,
        "w52_high":     w52_high,
        "above30_low":  w52_low * 1.30 if pd.notna(w52_low) else float("nan"),
        "within25_high": w52_high * 0.75 if pd.notna(w52_high) else float("nan"),
    }


# ---------------------------------------------------------------------------
# D-6: 7-condition evaluation
# ---------------------------------------------------------------------------

def _gt(a: float, b: float) -> bool:
    """Safe greater-than: NaN propagates to False."""
    try:
        return float(a) > float(b)
    except (TypeError, ValueError):
        return False


def check_conditions(metrics: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the 7 upward-trend conditions.

    Returns a dict with keys c1..c7 (bool) and selected (bool).
    Any NaN metric causes the corresponding condition to be False.
    """
    p    = metrics.get("price",        float("nan"))
    m200 = metrics.get("ma200",        float("nan"))
    m150 = metrics.get("ma150",        float("nan"))
    m50  = metrics.get("ma50",         float("nan"))
    m200_ago = metrics.get("ma200_1mago", float("nan"))
    abv30    = metrics.get("above30_low", float("nan"))
    w25      = metrics.get("within25_high", float("nan"))

    c1 = _gt(p, m200) and _gt(p, m150)       # price above both LT MAs
    c2 = _gt(m150, m200)                       # MA150 > MA200 (upward alignment)
    c3 = _gt(m200, m200_ago)                   # MA200 trending up
    c4 = _gt(m50, m200) and _gt(m50, m150)    # MA50 above both LT MAs
    c5 = _gt(p, m50)                           # price above MA50
    c6 = _gt(p, abv30)                         # ≥ 30% above 52W low
    c7 = _gt(p, w25)                           # within 25% of 52W high

    selected = c1 and c2 and c3 and c4 and c5 and c6 and c7
    return {
        "c1": c1, "c2": c2, "c3": c3, "c4": c4,
        "c5": c5, "c6": c6, "c7": c7,
        "selected": selected,
    }

