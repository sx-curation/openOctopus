"""
CacheManager: unified L1 / L2 / L3 cache interface.

Layer  Storage            TTL default  Notes
-----  -----------------  -----------  -----------------------------------
L1     In-memory dict     300 s        Wraps existing utils/cache.py logic
L2     Disk JSON          86400 s      .cache/tool_cache/{tool}/{ticker}.json
L3     (placeholder)      —            NotImplementedError; reserved for Foundry

Usage
-----
from utils.cache_manager import cache

cache.set(1, "get_stock_price", "AAPL", {"price": 175.0})
value = cache.get(1, "get_stock_price", "AAPL")   # → {"price": 175.0}

cache.set(2, "get_key_financials", "AAPL", {...})  # written to disk atomically
"""
import json
import os
import tempfile
import time
from typing import Any


class CacheManager:
    """Three-layer cache: L1 in-memory, L2 disk-JSON, L3 placeholder."""

    _DEFAULT_TTL = {1: 300, 2: 86400}

    def __init__(self, cache_dir: str = ".cache/tool_cache") -> None:
        # L1 store: key → (expires_monotonic, value)
        self._l1: dict[str, tuple[float, Any]] = {}
        self._cache_dir = cache_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, layer: int, tool_name: str, ticker: str) -> Any | None:
        """Retrieve a cached value.

        Returns ``None`` on miss, expired entry, or L3 (always None).
        """
        key = self._key(tool_name, ticker)
        if layer == 1:
            return self._l1_get(key)
        if layer == 2:
            return self._l2_get(tool_name, ticker)
        if layer == 3:
            return None
        raise ValueError(f"Unknown cache layer: {layer}")

    def set(self, layer: int, tool_name: str, ticker: str, value: Any, ttl: int | None = None) -> None:
        """Store a value in the given layer.

        Raises ``NotImplementedError`` for layer 3.
        """
        if layer == 1:
            effective_ttl = ttl if ttl is not None else self._DEFAULT_TTL[1]
            self._l1_set(self._key(tool_name, ticker), value, effective_ttl)
        elif layer == 2:
            effective_ttl = ttl if ttl is not None else self._DEFAULT_TTL[2]
            self._l2_set(tool_name, ticker, value, effective_ttl)
        elif layer == 3:
            raise NotImplementedError("L3 not implemented: reserved for Foundry artifact")
        else:
            raise ValueError(f"Unknown cache layer: {layer}")

    def clear_l1(self) -> None:
        """Flush the entire L1 in-memory store (useful in tests)."""
        self._l1.clear()

    # ------------------------------------------------------------------
    # L1 helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(tool_name: str, ticker: str) -> str:
        return f"{tool_name}::{ticker.upper()}"

    def _l1_get(self, key: str) -> Any | None:
        entry = self._l1.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._l1[key]
            return None
        return value

    def _l1_set(self, key: str, value: Any, ttl: int) -> None:
        self._l1[key] = (time.monotonic() + ttl, value)

    # ------------------------------------------------------------------
    # L2 helpers
    # ------------------------------------------------------------------

    def _l2_path(self, tool_name: str, ticker: str) -> str:
        return os.path.join(self._cache_dir, tool_name, f"{ticker.upper()}.json")

    def _l2_get(self, tool_name: str, ticker: str) -> Any | None:
        path = self._l2_path(tool_name, ticker)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                envelope = json.load(fh)
            expires_at = envelope.get("expires_at", 0)
            if time.time() > expires_at:
                return None
            return envelope.get("data")
        except (OSError, json.JSONDecodeError, KeyError):
            return None

    def _l2_set(self, tool_name: str, ticker: str, value: Any, ttl: int) -> None:
        path = self._l2_path(tool_name, ticker)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        envelope = {"expires_at": time.time() + ttl, "data": value}

        # Atomic write: temp file in same directory → os.replace
        dir_path = os.path.dirname(path)
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh)
            os.replace(tmp_path, path)
        except Exception:
            # Clean up temp file on failure; re-raise so callers know
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
cache = CacheManager()
