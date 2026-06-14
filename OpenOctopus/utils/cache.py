"""
Simple in-memory TTL cache for tool results.
Keyed on (tool_name, ticker) to avoid redundant API calls within a session.
"""
import time
from typing import Any

_store: dict[tuple, tuple[float, Any]] = {}


def get(tool_name: str, ticker: str) -> Any | None:
    key = (tool_name, ticker.upper())
    entry = _store.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
        del _store[key]
        return None
    return value


def set(tool_name: str, ticker: str, value: Any, ttl: int) -> None:
    key = (tool_name, ticker.upper())
    _store[key] = (time.monotonic() + ttl, value)


def clear() -> None:
    _store.clear()
