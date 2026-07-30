"""TWSE 三大法人買賣超日報 (T86) data fetcher.

Fetches institutional investor (foreign / domestic fund / dealer) daily
net buy/sell data from the Taiwan Stock Exchange open-data API.

Rate limit: TWSE blocks aggressive crawlers. Use request_delay >= 1.0 s.
"""
import datetime as dt
import time
from typing import Dict, List, Any, Optional

import requests


# ── TWSE T86 endpoint ─────────────────────────────────────────────────────────
_T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://www.twse.com.tw/zh/trading/fund/T86.html",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


def _parse_int(s: Any) -> int:
    """Strip commas and parse TWSE number strings to int.  Returns 0 on error."""
    try:
        return int(str(s).replace(",", "").replace(" ", "").strip())
    except (ValueError, AttributeError):
        return 0


def _col_index(fields: List[str], *keywords: str) -> int:
    """Return first field index containing ALL keywords; -1 if not found."""
    for i, f in enumerate(fields):
        if all(kw in f for kw in keywords):
            return i
    return -1


def fetch_t86_day(
    date_str: str, request_delay: float = 1.0
) -> Dict[str, Any]:
    """Fetch 三大法人 net buy/sell (shares) for ALL TWSE stocks on one date.

    Args:
        date_str: Date in YYYYMMDD format (e.g., '20250630').
        request_delay: Seconds to sleep before the HTTP request.

    Returns:
        On success: dict mapping stock_id (str) → {foreign_net, fund_net,
                    dealer_net, total_net}  (all values are int, unit = shares).
        On holiday / no data: {'holiday': True, 'date': date_str}
        On error: {'error': str, 'date': date_str}
    """
    if request_delay > 0:
        time.sleep(request_delay)

    params = {
        "response": "json",
        "date": date_str,
        "selectType": "ALLBUT0999",   # common stocks only
    }
    try:
        resp = requests.get(_T86_URL, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        jdata = resp.json()
    except Exception as exc:
        return {"error": str(exc), "date": date_str}

    # TWSE returns stat field when no data (holiday / future date)
    stat = jdata.get("stat", "")
    if "很抱歉" in stat or not jdata.get("data"):
        return {"holiday": True, "date": date_str}

    fields: List[str] = jdata.get("fields", [])
    rows: List[List] = jdata.get("data", [])

    # ── Identify column indices ────────────────────────────────────────────────
    # Try name-based matching first; fall back to known positional defaults.
    # T86 layout (19 columns, as of 2026):
    #  0  證券代號
    #  1  證券名稱
    #  2–4  外資及陸資(不含外資自營商) buy/sell/net  ← idx_foreign = 4
    #  5–7  外資自營商 buy/sell/net
    #  8–10 投信 buy/sell/net                        ← idx_fund = 10
    #  11   自營商-買賣超股數 (combined)              ← idx_dealer = 11
    #  12–14 自營商(自行買賣) buy/sell/net
    #  15–17 自營商(避險) buy/sell/net
    #  18   三大法人買賣超股數                        ← idx_total = 18

    idx_foreign = _col_index(fields, "外資及陸資", "買賣超股數")
    idx_fund    = _col_index(fields, "投信", "買賣超股數")
    idx_dealer  = _col_index(fields, "自營商-買賣超股數")
    idx_total   = _col_index(fields, "三大法人買賣超股數")

    # Positional fallbacks for 19-col layout
    if idx_foreign < 0: idx_foreign = 4
    if idx_fund    < 0: idx_fund    = 10
    if idx_dealer  < 0: idx_dealer  = 11
    if idx_total   < 0: idx_total   = 18

    need = max(idx_foreign, idx_fund, idx_dealer, idx_total)
    result: Dict[str, Dict] = {}
    for row in rows:
        if len(row) <= need:
            continue
        stock_id = str(row[0]).strip()
        if not stock_id or not stock_id.isdigit():
            continue
        result[stock_id] = {
            "foreign_net": _parse_int(row[idx_foreign]),
            "fund_net":    _parse_int(row[idx_fund]),
            "dealer_net":  _parse_int(row[idx_dealer]),
            "total_net":   _parse_int(row[idx_total]),
        }

    return result


def get_recent_trading_dates(days_back: int = 100) -> List[str]:
    """Return weekday dates (YYYYMMDD) going back N calendar days, newest first.

    Actual holidays are filtered downstream when the API returns no data.
    """
    today = dt.date.today()
    return [
        (today - dt.timedelta(days=i)).strftime("%Y%m%d")
        for i in range(days_back)
        if (today - dt.timedelta(days=i)).weekday() < 5   # Mon–Fri
    ]


def fetch_range_for_stock(
    stock_id: str,
    existing_dates: Optional[set] = None,
    target_trading_days: int = 60,
    request_delay: float = 1.0,
    on_progress=None,
) -> List[Dict[str, Any]]:
    """Fetch up to target_trading_days of 三大法人 data for one stock.

    Skips dates already in existing_dates (DB cache).
    Returns list of dicts ready for DB insertion:
        {stock_id, date (YYYY-MM-DD), foreign_net, fund_net, dealer_net, total_net}

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
            # Too many consecutive holidays — probably gone too far back
            break

        day_data = fetch_t86_day(date_str, request_delay=request_delay)

        if day_data.get("holiday") or "error" in day_data:
            holiday_streak += 1
            continue
        holiday_streak = 0

        stock_data = day_data.get(stock_id)
        if stock_data is None:
            # Stock not in the T86 response for this date (delisted? TPEx?)
            continue

        date_fmt = dt.datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
        collected.append({
            "stock_id":   stock_id,
            "date":       date_fmt,
            "foreign_net": stock_data["foreign_net"],
            "fund_net":    stock_data["fund_net"],
            "dealer_net":  stock_data["dealer_net"],
            "total_net":   stock_data["total_net"],
        })

        if on_progress:
            on_progress(len(collected), target_trading_days)

    return collected
