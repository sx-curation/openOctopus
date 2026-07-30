"""A-share concept/sector tags via AKShare. 24-hour cache, lazy background build."""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE = Path(".cache/ashare/concept_index.json")
_TTL = 86400  # 24 hours
_build_lock = threading.Lock()
_building = False


def _build_index() -> dict[str, list[str]]:
    """Build inverted index: bare_code -> [concept_names]. Calls ~100 AKShare requests."""
    try:
        import akshare as ak
    except ImportError:
        return {}
    index: dict[str, list[str]] = {}
    try:
        df = ak.stock_board_concept_name_em()
        concepts = df["板块名称"].head(100).tolist()
    except Exception:
        return {}
    for concept in concepts:
        try:
            members = ak.stock_board_concept_cons_em(symbol=concept)
            code_col = members.columns[0]
            for code in members[code_col].astype(str).str.zfill(6).tolist():
                index.setdefault(code, []).append(concept)
            time.sleep(0.08)
        except Exception:
            continue
    return index


def _cache_fresh() -> bool:
    return _CACHE.exists() and (time.time() - _CACHE.stat().st_mtime) < _TTL


def _load_cache() -> dict[str, list[str]]:
    try:
        with _CACHE.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(index: dict) -> None:
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    with _CACHE.open("w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)


def _background_build() -> None:
    global _building
    with _build_lock:
        if _building:
            return
        _building = True
    try:
        logger.info("ashare concept_tags: building index in background (~2 min)...")
        index = _build_index()
        if index:
            _save_cache(index)
            logger.info("ashare concept_tags: index built, %d stocks tagged", len(index))
    except Exception as exc:
        logger.warning("ashare concept_tags: build failed: %s", exc)
    finally:
        _building = False


def get_concept_tags(ticker: str) -> list[str]:
    """Return concept tags for ticker. Returns [] immediately if cache not ready."""
    from . import strip_suffix
    code = strip_suffix(ticker)
    if _cache_fresh():
        return _load_cache().get(code, [])
    # Trigger background build; return empty for now
    t = threading.Thread(target=_background_build, daemon=True)
    t.start()
    return []
