"""Dragon Tiger Board (龙虎榜) data for A-shares.

Uses AKShare stock_lhb_detail_em — only available on limit-up/limit-down days.
Returns {"available": false, "reason": "no_lhb_in_7d"} when no data found.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from services.ashare import strip_suffix

logger = logging.getLogger(__name__)

# Columns of interest (use col index as fallback if name lookup fails)
_COL_CODE   = "代码"
_COL_NAME   = "名称"
_COL_DATE   = "上榜日"
_COL_REASON = "上榜原因"
_COL_CLOSE  = "收盘价"
_COL_CHG    = "涨跌幅"
_COL_NET    = "龙虎榜净买额"


def fetch_dragon_tiger(ticker: str) -> dict:
    """Return dragon tiger board entries for ticker within the last 7 days."""
    import akshare as ak

    code = strip_suffix(ticker)
    end   = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=7)).strftime("%Y%m%d")
    try:
        df = ak.stock_lhb_detail_em(start_date=start, end_date=end)
        if df is None or df.empty:
            return {"available": False, "reason": "no_lhb_in_7d"}

        # Filter by code (col index 1 = 代码)
        code_col = _COL_CODE if _COL_CODE in df.columns else df.columns[1]
        sub = df[df[code_col].astype(str).str.zfill(6) == code]
        if sub.empty:
            return {"available": False, "reason": "no_lhb_in_7d"}

        entries = []
        for _, row in sub.iterrows():
            entry = {}
            for col_name, key in [
                (_COL_DATE,   "date"),
                (_COL_REASON, "reason"),
                (_COL_CLOSE,  "close"),
                (_COL_CHG,    "change_pct"),
                (_COL_NET,    "net_buy"),
            ]:
                if col_name in sub.columns:
                    v = row[col_name]
                    entry[key] = _clean_val(v)
            entries.append(entry)

        return {"available": True, "entries": entries}
    except Exception as e:
        logger.debug("dragon_tiger.fetch_dragon_tiger: %s: %s", ticker, e)
        return {"available": False, "reason": "fetch_error"}


def _clean_val(v):
    """Convert pandas Timestamp → ISO string; NaN → None; else pass through."""
    import math
    if v is None:
        return None
    try:
        # pandas Timestamp
        if hasattr(v, "isoformat"):
            return str(v)[:10]
    except Exception:
        pass
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        pass
    return str(v) if not isinstance(v, (int, float, bool, str)) else v
