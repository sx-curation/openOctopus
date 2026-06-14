"""A-share margin trading data (融资融券).

SSE (SH): ak.stock_margin_detail_sse(date=YYYYMMDD)
  Columns: 0=信用交易日期, 1=标的证券代码, 2=标的证券简称,
           3=融资余额, 4=融资买入额, 5=融资偿还额,
           6=融券余量, 7=融券卖出量, 8=融券偿还量

SZSE (SZ): direct SZSE HTTP → openpyxl
  Columns: 0=证券代码, 1=证券简称, 2=融资买入额(元),
           3=融资余额(元), 4=融券卖出量, 5=融券余量,
           6=融券余额(元), 7=融资融券余额(元)

AKShare stock_margin_detail_szse has a bug in 1.18.64 (AttributeError on .str
accessor for a numeric column), so we fetch SZSE data directly via requests.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from io import BytesIO

import requests

from services.ashare import strip_suffix

logger = logging.getLogger(__name__)

_MAX_LOOKBACK_DAYS = 7

_SZSE_URL = "https://www.szse.cn/api/report/ShowReport"
_SZSE_HEADERS = {
    "Referer": "https://www.szse.cn/disclosure/margin/margin/index.html",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def _try_sse(code: str, d: date) -> dict | None:
    """Fetch SSE margin data for given date. Returns dict or None."""
    import akshare as ak
    df = ak.stock_margin_detail_sse(date=d.strftime("%Y%m%d"))
    if df is None or df.empty:
        return None
    # col 1 = 标的证券代码 (code), col 3 = 融资余额, col 6 = 融券余量
    row = df[df.iloc[:, 1].astype(str).str.zfill(6) == code]
    if row.empty:
        return None
    r = row.iloc[0]
    return {
        "margin_balance":     _parse_num(r.iloc[3]),   # 融资余额
        "short_balance":      _parse_num(r.iloc[6]),   # 融券余量 (shares)
        "short_interest_pct": None,
        "available":          True,
        "data_source":        "akshare_sse",
        "data_date":          d.isoformat(),
    }


def _try_szse(code: str, d: date) -> dict | None:
    """Fetch SZSE margin data via direct HTTP (bypasses AKShare bug)."""
    import pandas as pd
    params = {
        "SHOWTYPE":   "xlsx",
        "CATALOGID":  "1837_xxpl",
        "txtDate":    d.strftime("%Y-%m-%d"),
        "tab2PAGENO": "1",
        "random":     "0.5",
        "TABKEY":     "tab2",
    }
    try:
        resp = requests.get(_SZSE_URL, params=params, headers=_SZSE_HEADERS, timeout=12)
        resp.raise_for_status()
        import warnings
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            df = pd.read_excel(BytesIO(resp.content), engine="openpyxl", dtype={"证券代码": str})
        if df is None or df.empty:
            return None
    except Exception as e:
        logger.debug("margin._try_szse: HTTP error for %s: %s", d, e)
        return None

    # col 0=证券代码, col 3=融资余额(元), col 6=融券余额(元)
    row = df[df.iloc[:, 0].astype(str).str.zfill(6) == code]
    if row.empty:
        return None
    r = row.iloc[0]
    return {
        "margin_balance":     _parse_num(r.iloc[3]),   # 融资余额(元)
        "short_balance":      _parse_num(r.iloc[6]),   # 融券余额(元)
        "short_interest_pct": None,
        "available":          True,
        "data_source":        "szse_direct",
        "data_date":          d.isoformat(),
    }


def _parse_num(v) -> float | None:
    """Parse a value that may be a number or a comma-formatted string."""
    if v is None:
        return None
    try:
        if isinstance(v, str):
            v = v.replace(",", "").strip()
        return float(v) if v != "" else None
    except (TypeError, ValueError):
        return None


def fetch_margin(ticker: str) -> dict:
    """Return margin trading data for ticker, looking back up to _MAX_LOOKBACK_DAYS."""
    code = strip_suffix(ticker)
    is_sh = ticker.upper().endswith(".SH")
    fetcher = _try_sse if is_sh else _try_szse

    for offset in range(_MAX_LOOKBACK_DAYS):
        d = date.today() - timedelta(days=offset)
        try:
            result = fetcher(code, d)
            if result:
                return result
        except Exception as e:
            logger.debug("margin.fetch_margin: %s offset=%d error: %s", ticker, offset, e)
            continue

    return {
        "margin_balance":     None,
        "short_balance":      None,
        "short_interest_pct": None,
        "available":          False,
        "data_source":        "none",
    }
