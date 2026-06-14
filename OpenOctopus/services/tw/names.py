"""TW company Chinese name map — fetches from TWSE & TPEX open APIs.

Cache: .cache/screener/tw_names.json  (TTL 7 days)
Reuse-path: services/backlog/refresh.py → get_tw_name_map()
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_CACHE_DIR = Path('.cache/screener')
_CACHE_PATH = _CACHE_DIR / 'tw_names.json'
_TTL = 7 * 24 * 3600  # 7 days

# TWSE open-data — listed company info
_TWSE_URL = 'https://opendata.twse.com.tw/v1/opendata/t187ap03_L'
# TPEX open-data — OTC listed company info
_TPEX_URL = 'https://www.tpex.org.tw/openapi/v1/tpex_mainboard_perstock_info'

# Possible field name variants for code / short-name across API versions
_CODE_KEYS_TWSE = ('公司代號', 'stockCode', 'code', 'Code')
_NAME_KEYS_TWSE = ('公司簡稱', '公司名稱', 'shortName', 'name', 'Name')
_CODE_KEYS_TPEX = ('SecCode', '股票代號', 'code', 'Code')
_NAME_KEYS_TPEX = ('CompanyAbbr', '公司簡稱', 'CompanyName', '公司名稱', 'name')

_tw_name_map: dict | None = None


def _first_val(row: dict, keys: tuple) -> str:
    for k in keys:
        v = row.get(k)
        if v:
            return str(v).strip()
    return ''


def _fetch_twse() -> dict[str, str]:
    """Return {code: zh_abbr} for TWSE listed stocks."""
    resp = requests.get(_TWSE_URL, timeout=15)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return {}
    # Log first row keys once to aid debugging if field names change
    logger.debug('twse names row[0] keys: %s', list(rows[0].keys()))
    out: dict[str, str] = {}
    for row in rows:
        code = _first_val(row, _CODE_KEYS_TWSE)
        name = _first_val(row, _NAME_KEYS_TWSE)
        if code and name:
            out[code] = name
    if not out:
        logger.warning('twse names: 0 entries extracted; row[0]=%s', rows[0])
    return out


def _fetch_tpex() -> dict[str, str]:
    """Return {code: zh_abbr} for TPEX (OTC) listed stocks."""
    resp = requests.get(_TPEX_URL, timeout=15)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return {}
    logger.debug('tpex names row[0] keys: %s', list(rows[0].keys()))
    out: dict[str, str] = {}
    for row in rows:
        code = _first_val(row, _CODE_KEYS_TPEX)
        name = _first_val(row, _NAME_KEYS_TPEX)
        if code and name:
            out[code] = name
    if not out:
        logger.warning('tpex names: 0 entries extracted; row[0]=%s', rows[0])
    return out


def refresh_tw_name_cache() -> dict[str, str]:
    """Fetch fresh names from TWSE + TPEX and write to cache. Returns merged map."""
    names: dict[str, str] = {}
    for fn, label in [(_fetch_twse, 'TWSE'), (_fetch_tpex, 'TPEX')]:
        try:
            batch = fn()
            names.update(batch)
            logger.info('tw names: %s returned %d entries', label, len(batch))
        except Exception as e:
            logger.warning('tw names: %s fetch failed: %s', label, e)
    if names:
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _CACHE_PATH.write_text(
                json.dumps({'ts': time.time(), 'names': names}, ensure_ascii=False),
                encoding='utf-8',
            )
            logger.info('tw names: cached %d entries to %s', len(names), _CACHE_PATH)
        except Exception as e:
            logger.warning('tw names: cache write failed: %s', e)
    return names


def get_tw_name_map(force_refresh: bool = False) -> dict[str, str]:
    """Lazy-load TW name map. Re-fetches from API if cache is stale (>7 days) or missing."""
    global _tw_name_map
    if _tw_name_map is not None and not force_refresh:
        return _tw_name_map

    if not force_refresh and _CACHE_PATH.exists():
        try:
            data = json.loads(_CACHE_PATH.read_text(encoding='utf-8'))
            if time.time() - float(data.get('ts', 0)) < _TTL:
                _tw_name_map = data['names']
                return _tw_name_map
        except Exception as e:
            logger.debug('tw names: cache read failed: %s', e)

    _tw_name_map = refresh_tw_name_cache() or {}
    return _tw_name_map
