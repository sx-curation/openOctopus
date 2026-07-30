"""
Disk-backed TTL cache for policy source adapters.
Uses Python's built-in shelve module — no extra dependencies.
Cache directory and TTL configured via config/settings.py.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shelve
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DiskCache:
    """
    Key-value cache stored on disk (shelve / dbm).

    Keys are derived from (namespace, params_dict) — params are JSON-serialised
    and hashed so any dict can be a cache key.

    Values are stored as (expires_at: float, data: Any) tuples.
    Expired entries are lazily evicted on next read.
    """

    def __init__(self, cache_dir: str = ".cache/policy_monitoring", ttl_seconds: int = 3600):
        self.ttl = ttl_seconds
        self._path = Path(cache_dir)
        self._path.mkdir(parents=True, exist_ok=True)
        self._db_path = str(self._path / "cache")

    # ------------------------------------------------------------------

    def _key(self, namespace: str, params: dict) -> str:
        raw = namespace + ":" + json.dumps(params, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    # ------------------------------------------------------------------

    def get(self, namespace: str, params: dict) -> Optional[Any]:
        """Return cached value or None if missing / expired."""
        key = self._key(namespace, params)
        try:
            with shelve.open(self._db_path, flag="r") as db:
                if key not in db:
                    return None
                expires_at, value = db[key]
                if time.monotonic() > expires_at:
                    logger.debug("cache expired key=%s…", key[:8])
                    return None
                logger.debug("cache_hit namespace=%s key=%s…", namespace, key[:8])
                return value
        except Exception as exc:
            # shelve can fail on first open (file doesn't exist yet)
            logger.debug("cache read skipped: %s", exc)
            return None

    def set(self, namespace: str, params: dict, value: Any) -> None:
        """Store value with TTL expiry."""
        key = self._key(namespace, params)
        try:
            with shelve.open(self._db_path) as db:
                db[key] = (time.monotonic() + self.ttl, value)
        except Exception as exc:
            logger.warning("cache write failed: %s", exc)

    def delete(self, namespace: str, params: dict) -> None:
        key = self._key(namespace, params)
        try:
            with shelve.open(self._db_path) as db:
                if key in db:
                    del db[key]
        except Exception as exc:
            logger.warning("cache delete failed: %s", exc)

    def clear(self) -> None:
        try:
            with shelve.open(self._db_path) as db:
                db.clear()
            logger.info("policy cache cleared")
        except Exception as exc:
            logger.warning("cache clear failed: %s", exc)

    def evict_expired(self) -> int:
        """Remove all expired entries; return count removed."""
        removed = 0
        now = time.monotonic()
        try:
            with shelve.open(self._db_path) as db:
                expired_keys = [k for k, (exp, _) in db.items() if now > exp]
                for k in expired_keys:
                    del db[k]
                removed = len(expired_keys)
        except Exception as exc:
            logger.warning("cache eviction failed: %s", exc)
        return removed
