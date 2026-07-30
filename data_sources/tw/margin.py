"""TWSE 融資融券彙總 (MI_MARGN) data fetcher.

Fetches margin trading (融資) and short selling (融券) balance data for all
TWSE-listed stocks from the Taiwan Stock Exchange open-data API.

Rate limit: TWSE blocks aggressive crawlers. Use request_delay >= 1.0 s.

Response column layout (16 cols, 0-indexed):
  0  代號 (stock_id)
  1  名稱
  2  融資買進    (margin_buy)
  3  融資賣出    (margin_sell)
  4  融資現金償還
  5  融資前日餘額
  6  融資今日餘額 (margin_balance)
  7  融資次一營業日限額
  8  融券買進    (short_cover)
  9  融券賣出    (short_sell)
  10 融券現券償還
  11 融券前日餘額
  12 融券今日餘額 (short_balance)
  13 融券次一營業日限額
  14 資券互抵
  15 註記
"""
import datetime as dt
import time
from typing import Any, Dict, List, Optional

import requests


_MARGN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://www.twse.com.tw/zh/trading/margin/MI_MARGN.html",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

# Column indices (0-based) in the per-stock data array
_IDX_ID             = 0
_IDX_MARGIN_BUY     = 2
_IDX_MARGIN_SELL    = 3
_IDX_MARGIN_BAL     = 6
_IDX_SHORT_COVER    = 8
_IDX_SHORT_SELL     = 9
_IDX_SHORT_BAL      = 12
_MIN_COLS           = 13   # must have at least this many columns


def _parse_int(s: Any) -> int:
    """Strip commas and parse TWSE number strings to int. Returns 0 on error."""
    try:
        return int(str(s).replace(",", "").replace(" ", "").strip())
    except (ValueError, AttributeError):
        return 0


def fetch_margin_day(
    date_str: str, request_delay: float = 1.0
) -> Dict[str, Any]:
    """Fetch margin/short balances for ALL TWSE stocks on one date.

    Args:
        date_str: Date in YYYYMMDD format (e.g., '20250630').
        request_delay: Seconds to sleep before the HTTP request.

    Returns:
        On success: dict mapping stock_id (str) → {margin_balance, margin_buy,
                    margin_sell, short_balance, short_sell, short_cover}
        On holiday / no data: {'holiday': True, 'date': date_str}
        On error: {'error': str, 'date': date_str}
    """
    if request_delay > 0:
        time.sleep(request_delay)

    params = {
        "response":   "json",
        "date":       date_str,
        "selectType": "ALL",
    }
    try:
        resp = requests.get(_MARGN_URL, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        jdata = resp.json()
    except Exception as exc:
        return {"error": str(exc), "date": date_str}

    # TWSE wraps per-stock table inside tables[1] (index 1)
    # tables[0] is the market-wide summary row
    tables = jdata.get("tables", [])
    stat   = jdata.get("stat", "")

    # Locate the per-stock table (title contains 融資融券 and has many rows)
    per_stock_data: List[List] = []
    for tbl in tables:
        rows = tbl.get("data", [])
        if rows and len(rows) > 5:
            per_stock_data = rows
            break

    if "很抱歉" in stat or not per_stock_data:
        return {"holiday": True, "date": date_str}

    result: Dict[str, Dict] = {}
    for row in per_stock_data:
        if len(row) < _MIN_COLS:
            continue
        stock_id = str(row[_IDX_ID]).strip()
        if not stock_id or not stock_id.isdigit():
            continue
        result[stock_id] = {
            "margin_balance": _parse_int(row[_IDX_MARGIN_BAL]),
            "margin_buy":     _parse_int(row[_IDX_MARGIN_BUY]),
            "margin_sell":    _parse_int(row[_IDX_MARGIN_SELL]),
            "short_balance":  _parse_int(row[_IDX_SHORT_BAL]),
            "short_sell":     _parse_int(row[_IDX_SHORT_SELL]),
            "short_cover":    _parse_int(row[_IDX_SHORT_COVER]),
        }

    return result


def get_recent_trading_dates(days_back: int = 150) -> List[str]:
    """Return weekday dates (YYYYMMDD) going back N calendar days, newest first."""
    today = dt.date.today()
    return [
        (today - dt.timedelta(days=i)).strftime("%Y%m%d")
        for i in range(days_back)
        if (today - dt.timedelta(days=i)).weekday() < 5
    ]


def fetch_margin_range_for_stock(
    stock_id: str,
    existing_dates: Optional[set] = None,
    target_trading_days: int = 120,
    request_delay: float = 1.0,
    on_progress=None,
) -> List[Dict[str, Any]]:
    """Fetch up to target_trading_days of margin/short data for one stock.

    Skips dates already in existing_dates (DB cache).
    Returns list of dicts ready for DB insertion:
        {stock_id, date (YYYY-MM-DD), margin_balance, margin_buy, margin_sell,
         short_balance, short_sell, short_cover}

    Args:
        on_progress: optional callable(fetched, total_needed) for progress updates.
    """
    existing_dates = existing_dates or set()
    calendar_dates = get_recent_trading_dates(days_back=target_trading_days * 2 + 30)
    missing = [
        d for d in calendar_dates
        if dt.datetime.strptime(d, "%Y%m%d").strftime("%Y-%m-%d") not in existing_dates
    ]

    collected: List[Dict] = []
    holiday_streak = 0

    for date_str in missing:
        if len(collected) >= target_trading_days:
            break
        if holiday_streak >= 10:
            break

        day_data = fetch_margin_day(date_str, request_delay=request_delay)

        if day_data.get("holiday") or "error" in day_data:
            holiday_streak += 1
            continue
        holiday_streak = 0

        stock_data = day_data.get(stock_id)
        if stock_data is None:
            # Stock not in margin list for this date (ETF, delisted, etc.)
            # Count as a valid day to avoid over-fetching
            date_fmt = dt.datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
            collected.append({
                "stock_id":       stock_id,
                "date":           date_fmt,
                "margin_balance": 0,
                "margin_buy":     0,
                "margin_sell":    0,
                "short_balance":  0,
                "short_sell":     0,
                "short_cover":    0,
            })
        else:
            date_fmt = dt.datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
            collected.append({
                "stock_id":   stock_id,
                "date":       date_fmt,
                **stock_data,
            })

        if on_progress:
            on_progress(len(collected), target_trading_days)

    return collected
