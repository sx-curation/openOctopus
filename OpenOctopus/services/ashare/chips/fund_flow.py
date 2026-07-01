"""A-share individual stock main-force fund flow (主力資金淨流入).

Primary source: Tonghuashun (同花順) per-page binary-search.
  - Generates hexin-v token via py_mini_racer + akshare's ths.js
  - Binary-searches the code-sorted ranking to find the target stock's page
    (typically ~7 HTTP requests), then fetches both today and 3-day data
    from the same page number (pages are identical across both time windows)
  - Page numbers are cached per-code for 24 hours to reduce requests on reload

Fallback: East Money push2his daykline endpoint (works when not IP-blocked).

Returns prev_day_net_inflow and avg_3d_net_inflow in 元.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from pathlib import Path
from typing import Optional

import requests

from services.ashare import strip_suffix

logger = logging.getLogger(__name__)

# ── East Money fallback (original) ───────────────────────────────────────────
_EM_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
_EM_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _secid(ticker: str) -> str:
    code = strip_suffix(ticker)
    prefix = "1" if ticker.upper().endswith(".SH") else "0"
    return f"{prefix}.{code}"


def _try_eastmoney(ticker: str) -> Optional[dict]:
    """Fallback: East Money push2his daykline. Works when endpoint is accessible."""
    params = {
        "lmt": 0, "klt": 101, "secid": _secid(ticker),
        "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
    }
    try:
        time.sleep(random.uniform(0.2, 0.5))
        resp = requests.get(_EM_URL, params=params, headers=_EM_HEADERS, timeout=8)
        resp.raise_for_status()
        klines = resp.json().get("data", {}).get("klines") or []
        if not klines:
            return None
        recent = klines[-3:]
        values = []
        for k in recent:
            try:
                values.append(float(k.split(",")[1]))
            except (IndexError, ValueError):
                pass
        if not values:
            return None
        return {
            "available": True,
            "prev_day_net_inflow": values[-1],
            "avg_3d_net_inflow": sum(values) / len(values),
        }
    except Exception as e:
        logger.debug("fund_flow._try_eastmoney %s: %s", ticker, e)
        return None


# ── Tonghuashun hexin-v context ──────────────────────────────────────────────
_THS_CTX: Optional[object] = None
_THS_CTX_LOCK = threading.Lock()


def _get_hexin_v() -> str:
    """Generate hexin-v token using akshare's ths.js + py_mini_racer."""
    global _THS_CTX
    with _THS_CTX_LOCK:
        if _THS_CTX is None:
            import py_mini_racer
            import akshare
            js_path = Path(akshare.__file__).parent / "stock_feature" / "ths.js"
            ctx = py_mini_racer.MiniRacer()
            ctx.eval(js_path.read_text("utf-8"))
            _THS_CTX = ctx
        return _THS_CTX.call("v")


# ── Page-number cache (code → page, valid 24 h) ───────────────────────────────
_PAGE_CACHE: dict[str, dict] = {}  # {code: {page: int, ts: float}}
_PAGE_CACHE_TTL = 86400  # 24 hours


def _parse_yuan(s: str) -> Optional[float]:
    """Parse THS display amount string to 元. e.g. '-9.90亿' → -9.9e8"""
    s = s.strip()
    try:
        if s.endswith("亿"):
            return float(s[:-1]) * 1e8
        if s.endswith("万"):
            return float(s[:-1]) * 1e4
        return float(s)
    except ValueError:
        return None


def _ths_fetch_page(page: int, board: str = "") -> dict[str, str]:
    """Fetch one Tonghuashun ranking page sorted by code ASC.

    Returns {code: net_amount_display_str}.
    board='': today (即时) data; board='3': 3-day cumulative data.
    """
    board_prefix = f"board/{board}/" if board else ""
    url = (
        f"http://data.10jqka.com.cn/funds/ggzjl/"
        f"{board_prefix}field/code/order/asc/page/{page}/ajax/1/free/1/"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "hexin-v": _get_hexin_v(),
        "Referer": "http://data.10jqka.com.cn/funds/ggzjl/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    time.sleep(random.uniform(0.3, 0.6))
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        from bs4 import BeautifulSoup
        content = r.content.decode("gbk", errors="replace")
        soup = BeautifulSoup(content, "html.parser")
        table = soup.find("table", class_="m-table")
        if not table:
            return {}
        result: dict[str, str] = {}
        for row in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            # today (即时): 10 cols → cells[8] = 净额
            # 3-day:         7 cols → cells[6] = 资金流入净额
            if board == "3" and len(cells) >= 7:
                result[cells[1]] = cells[6]
            elif board == "" and len(cells) >= 10:
                result[cells[1]] = cells[8]
        return result
    except Exception as e:
        logger.debug("fund_flow._ths_fetch_page page=%d board=%r: %s", page, board, e)
        return {}


def _ths_find_page(code: str, total_pages: int = 104) -> Optional[int]:
    """Binary-search for the page containing code (sorted by code ASC).

    Returns page number (1-based) or None if not found.
    Cached for 24 hours per code.
    """
    cached = _PAGE_CACHE.get(code)
    if cached and (time.time() - cached["ts"]) < _PAGE_CACHE_TTL:
        return cached["page"]

    lo, hi = 1, total_pages
    while lo <= hi:
        mid = (lo + hi) // 2
        page_data = _ths_fetch_page(mid)
        if not page_data:
            break
        if code in page_data:
            _PAGE_CACHE[code] = {"page": mid, "ts": time.time()}
            return mid
        codes = sorted(page_data.keys())
        last_code = codes[-1] if codes else None
        if last_code and last_code < code:
            lo = mid + 1
        else:
            hi = mid - 1
    return None


def _try_ths(ticker: str) -> Optional[dict]:
    """Primary: Tonghuashun binary-search fund flow."""
    code = strip_suffix(ticker)
    try:
        page = _ths_find_page(code)
        if page is None:
            return None

        # Both 即时 and 3日 use the same page number (both sorted by code ASC)
        today_data = _ths_fetch_page(page, board="")
        d3_data = _ths_fetch_page(page, board="3")

        net_today_str = today_data.get(code)
        if net_today_str is None:
            return None
        prev_day = _parse_yuan(net_today_str)
        if prev_day is None:
            return None

        avg_3d = prev_day  # default: use today if 3-day unavailable
        net_3d_str = d3_data.get(code)
        if net_3d_str:
            net_3d = _parse_yuan(net_3d_str)
            if net_3d is not None:
                avg_3d = net_3d / 3.0

        return {
            "available": True,
            "prev_day_net_inflow": prev_day,
            "avg_3d_net_inflow": avg_3d,
        }
    except Exception as e:
        logger.debug("fund_flow._try_ths %s: %s", ticker, e)
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_fund_flow(ticker: str) -> dict:
    """Return main-force net inflow for today and 3-day average (元).

    Returns:
        prev_day_net_inflow: today's main-force net inflow (元)
        avg_3d_net_inflow:   average of last 3 trading days' net inflow (元)
    """
    _empty = {"available": False, "prev_day_net_inflow": None, "avg_3d_net_inflow": None}

    result = _try_ths(ticker)
    if result:
        return result

    result = _try_eastmoney(ticker)
    if result:
        return result

    return _empty
