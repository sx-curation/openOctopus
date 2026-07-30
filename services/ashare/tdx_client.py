"""TDX connection pool with 3-second timeout.

Note: public TDX servers are in mainland China. If unreachable (timeout),
all callers fall back to Tencent Finance price fetcher automatically.
"""
from __future__ import annotations

import concurrent.futures
import threading

_SERVERS = [
    ("119.147.212.81", 7709),
    ("124.74.236.94", 7709),
    ("180.153.18.170", 7709),
]

_api = None
_lock = threading.Lock()


def _try_connect(ip: str, port: int, timeout: float = 3.0):
    try:
        from pytdx.hq import TdxHq_API
        api = TdxHq_API()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(api.connect, ip, port)
            try:
                ok = fut.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                return None
        return api if ok else None
    except Exception:
        return None


def get_api():
    global _api
    with _lock:
        if _api is not None:
            return _api
        for ip, port in _SERVERS:
            a = _try_connect(ip, port)
            if a:
                _api = a
                return _api
        raise RuntimeError("No TDX server reachable")


def reset_api():
    global _api
    with _lock:
        _api = None
