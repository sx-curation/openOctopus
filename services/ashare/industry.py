"""
A-share industry classification via Sina Finance sector data.

Strategy: Fetch all constituent stocks for each of Sina Finance's 49 industry
sectors, build a {ticker → sector_name} reverse map.

Cache: .cache/screener/em_industry_map.json  (TTL: 7 days)
Build time: ~70 s (49 sectors × 1 API call each), runs once per cache expiry.
While building: returns None for all tickers (graceful degradation).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(".cache/screener/em_industry_map.json")
_CACHE_TTL_DAYS = 7
_LOCK = threading.Lock()

_industry_map: dict[str, str] | None = None  # {ticker → sector_name}
_building = False


def _code_to_ticker(code: str) -> str:
    """Map 6-digit code to ticker with suffix."""
    c = code.zfill(6)
    if c.startswith("6"):
        return f"{c}.SH"
    if c.startswith("8") or c.startswith("4"):
        return f"{c}.BJ"
    return f"{c}.SZ"


def _fetch_sina_sectors() -> dict[str, str]:
    """Return {sina_label: sector_name} dict from Sina Finance."""
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
    return {label: val.split(",")[1] for label, val in data.items()}


def _read_cache() -> dict[str, str] | None:
    try:
        if not _CACHE_PATH.exists():
            return None
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        built_at = data.get("built_at", 0)
        age_days = (time.time() - built_at) / 86400
        if age_days > _CACHE_TTL_DAYS:
            return None
        return data.get("map") or None
    except Exception:
        return None


def _write_cache(industry_map: dict[str, str]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {"built_at": time.time(), "map": industry_map}
        tmp = _CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_CACHE_PATH)
        logger.info("industry: cache written (%d tickers)", len(industry_map))
    except Exception as e:
        logger.warning("industry: cache write failed: %s", e)


def _build_map_bg() -> None:
    """Background thread: build {ticker → sector_name} via Sina Finance."""
    global _industry_map, _building
    logger.info("industry: background build started (Sina Finance source)")
    try:
        import akshare as ak

        sectors = _fetch_sina_sectors()   # {label: name}
        tmp: dict[str, str] = {}

        for label, name in sectors.items():
            try:
                df = ak.stock_sector_detail(sector=label)
                for _, row in df.iterrows():
                    raw_code = str(row.get("code", "")).strip()
                    if not raw_code:
                        continue
                    code = raw_code.zfill(6)
                    ticker = _code_to_ticker(code)
                    if ticker not in tmp:   # first sector wins
                        tmp[ticker] = name
                time.sleep(0.3)
            except Exception as e:
                logger.debug("industry: skipped sector %s (%s): %s", label, name, e)
                continue

        with _LOCK:
            _industry_map = tmp
        _write_cache(tmp)
        logger.info("industry: Sina build done (%d tickers)", len(tmp))
    except Exception as e:
        logger.warning("industry: build failed: %s", e)
    finally:
        with _LOCK:
            _building = False


def get_industry(ticker: str) -> str | None:
    """Return Sina Finance sector name for ticker.

    Returns None while the map is still building or if the ticker is not found.
    Triggers a background build if the map is not loaded.
    """
    global _industry_map, _building

    with _LOCK:
        if _industry_map is not None:
            return _industry_map.get(ticker.upper()) or _industry_map.get(ticker)

        # Try disk cache first (fast path, no blocking)
        cached = _read_cache()
        if cached is not None:
            _industry_map = cached
            # If cache is getting stale (>6 days), trigger a silent refresh in background
            try:
                data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
                age_days = (time.time() - data.get("built_at", 0)) / 86400
                if age_days > 6 and not _building:
                    _building = True
                    threading.Thread(target=_build_map_bg, daemon=True).start()
            except Exception:
                pass
            return _industry_map.get(ticker.upper()) or _industry_map.get(ticker)

        # Cache miss — start background build, return None for now
        if not _building:
            _building = True
            threading.Thread(target=_build_map_bg, daemon=True).start()
        return None
