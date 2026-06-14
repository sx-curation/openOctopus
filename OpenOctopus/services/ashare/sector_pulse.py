"""
Industry prosperity indicator (行業景氣燈) via Sina Finance sector data.

Data source: http://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php
Cache: in-memory, TTL 60 minutes.

Algorithm:
  Daily change% (涨跌幅) > +1.5%  → green  (景氣)
  < -1.5%                         → red    (偏弱)
  otherwise                       → yellow (中性)

Sector names match those returned by industry.get_industry() (both use Sina Finance).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

_PULSE_TTL = 3600  # 60 minutes

_pulse_cache: dict[str, dict] | None = None
_pulse_ts: float = 0.0


def _refresh_pulse() -> None:
    global _pulse_cache, _pulse_ts
    import requests

    url = "http://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "http://finance.sina.com.cn/",
    }
    r = requests.get(url, headers=headers, timeout=10)
    raw = r.content.decode("gbk")
    start = raw.index("{")
    data = json.loads(raw[start: raw.rindex("}") + 1])

    result: dict[str, dict] = {}
    for rank, (label, val) in enumerate(data.items(), 1):
        try:
            parts = val.split(",")
            name = parts[1]
            chg_pct = float(parts[5])
            grade = "green" if chg_pct > 1.5 else ("red" if chg_pct < -1.5 else "yellow")
            result[name] = {"grade": grade, "net_pct": round(chg_pct, 2), "rank": rank}
        except Exception as e:
            logger.debug("sector_pulse: skip row %d: %s", rank, e)
            continue

    _pulse_cache = result
    _pulse_ts = time.time()
    logger.debug("sector_pulse: refreshed %d sectors", len(result))


def _fuzzy_match(name: str, cache: dict[str, dict]) -> dict | None:
    """Try exact, then prefix, then substring match for slight naming differences."""
    if name in cache:
        return cache[name]
    for k in cache:
        if k.startswith(name) or name.startswith(k):
            return cache[k]
    return None


def get_sector_pulse(industry_name: str) -> dict | None:
    """Return {grade, net_pct, rank, updated_at} for a Sina Finance sector name.

    Returns None on error or if no match found.
    Refreshes in-memory cache if stale (>60 min).
    """
    global _pulse_cache, _pulse_ts

    if _pulse_cache is None or time.time() - _pulse_ts > _PULSE_TTL:
        try:
            _refresh_pulse()
        except Exception as e:
            logger.warning("sector_pulse: refresh failed: %s", e)
            return None

    data = _fuzzy_match(industry_name, _pulse_cache)
    if data:
        updated_at = datetime.fromtimestamp(_pulse_ts).strftime("%H:%M")
        return {**data, "updated_at": updated_at}
    return None
