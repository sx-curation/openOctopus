"""A-share chips dispatcher.

Parallel execution of margin, northbound, top_holders, dragon_tiger, turnover.
Outputs align with the US chips schema for /api/chips/summary and /api/chips/institutional.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .dragon_tiger import fetch_dragon_tiger
from .margin import fetch_margin
from .northbound import fetch_northbound
from .top_holders import fetch_top_holders
from .turnover import fetch_turnover

logger = logging.getLogger(__name__)

_SUMMARY_TIMEOUT = 12    # seconds
_INST_TIMEOUT    = 15    # seconds


def fetch_cn_chips_summary(ticker: str) -> dict:
    """Parallel fetch for /api/chips/summary — aligns with US schema + CN extension fields.

    US keys kept: volume, short
    CN extension keys: northbound
    """
    tasks = {
        "short":      (fetch_margin,     ticker),
        "northbound": (fetch_northbound, ticker),
        "volume":     (fetch_turnover,   ticker),
    }
    results = _run_parallel(tasks, timeout=_SUMMARY_TIMEOUT)
    return {"ticker": ticker.upper(), "market": "CN_A", **results}


def fetch_cn_chips_institutional(ticker: str) -> dict:
    """Parallel fetch for /api/chips/institutional — aligns with US schema + CN extension fields.

    US keys kept: institutional, insider (null for CN), etf (null for CN)
    CN extension key: dragon_tiger
    """
    tasks = {
        "institutional": (fetch_top_holders, ticker),
        "dragon_tiger":  (fetch_dragon_tiger, ticker),
    }
    results = _run_parallel(tasks, timeout=_INST_TIMEOUT)
    return {
        "ticker":  ticker.upper(),
        "market":  "CN_A",
        "insider": None,   # A-shares have no Form 4 equivalent
        "etf":     None,   # No direct ETF holdings API for A-shares
        **results,
    }


def _run_parallel(tasks: dict, timeout: float) -> dict:
    results: dict = {}
    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        future_map = {ex.submit(fn, t): key for key, (fn, t) in tasks.items()}
        for future in as_completed(future_map, timeout=timeout):
            key = future_map[future]
            try:
                results[key] = future.result()
            except Exception as e:
                logger.warning("dispatcher: task %s failed: %s", key, e)
                results[key] = {"available": False, "error": str(e)}
    # Fill any tasks that timed out
    for key in tasks:
        if key not in results:
            results[key] = {"available": False, "error": "timeout"}
    return results
