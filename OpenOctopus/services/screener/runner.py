"""
services/screener/runner.py
============================
Batch runner for the upward-ticker screener.

Public API
----------
  start_screener(market)         -> str  (job_id)
  pause_screener(job_id)
  resume_screener(job_id)
  cancel_screener(job_id)
  get_screener_status(job_id)    -> dict
"""
from __future__ import annotations

import json
import random
import threading
import time
import uuid
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

from .price_fetcher import (
    MARKET_SP500, MARKET_NDX, MARKET_DAX, MARKET_TW50,
    MARKET_CN_CSI300, MARKET_CN_SZ100, MARKET_CN_GEM, MARKET_CN_STAR,
    RateLimitError,
    fetch_prices, compute_metrics, check_conditions,
)
from .ticker_sources import (
    get_sp500_tickers, get_nasdaq100_tickers, get_dax40_tickers, get_tw50_tickers,
    get_cn_csi300_tickers, get_cn_sz100_tickers, get_cn_gem_tickers, get_cn_star50_tickers,
)

# ---------------------------------------------------------------------------
# Cache directory (shared with ticker_sources)
# ---------------------------------------------------------------------------
_CACHE_DIR = Path(".cache") / "screener"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# E-1: Global state store
# ---------------------------------------------------------------------------
_SCREENER_STATE: dict[str, dict[str, Any]] = {}
_STATE_LOCK = threading.Lock()

_CN_MARKETS = (MARKET_CN_CSI300, MARKET_CN_SZ100, MARKET_CN_GEM, MARKET_CN_STAR)
_VALID_MARKETS = (MARKET_SP500, MARKET_NDX, MARKET_DAX, MARKET_TW50) + _CN_MARKETS

_cn_name_cache: dict | None = None

def _get_cn_name(ticker: str) -> str | None:
    """Lazy-load CN name map; return Chinese name or None."""
    global _cn_name_cache
    if _cn_name_cache is None:
        try:
            from services.ashare.names import get_cn_name_map
            _cn_name_cache = get_cn_name_map()
        except Exception:
            _cn_name_cache = {}
    return _cn_name_cache.get(ticker)


_tw_name_cache: dict | None = None

def _get_tw_name(ticker: str) -> str | None:
    """Lazy-load TW name map; return Chinese name or None.
    TW map keys are bare 4-digit codes (e.g. '2330'); strip '.TW' suffix before lookup.
    """
    global _tw_name_cache
    if _tw_name_cache is None:
        try:
            from services.tw.names import get_tw_name_map
            _tw_name_cache = get_tw_name_map()
        except Exception:
            _tw_name_cache = {}
    code = ticker.split('.')[0] if '.' in ticker else ticker
    return _tw_name_cache.get(code)


def _batch_size_for(market: str) -> int:
    sizes = {
        MARKET_SP500: 50, MARKET_NDX: 10, MARKET_DAX: 5, MARKET_TW50: 10,
        MARKET_CN_CSI300: 30, MARKET_CN_SZ100: 30, MARKET_CN_GEM: 30, MARKET_CN_STAR: 30,
    }
    return sizes.get(market, 10)


def _price_priority_for(market: str) -> list[str]:
    if market == MARKET_DAX:
        return ["yahoo", "stooq", "fmp"]
    if market == MARKET_TW50:
        return ["yahoo", "twse"]
    if market in _CN_MARKETS:
        return ["tencent", "tdx"]
    return ["stooq", "yahoo", "fmp"]


# ---------------------------------------------------------------------------
# E-2: Disk cache helpers
# ---------------------------------------------------------------------------

def _cache_path(market: str) -> Path:
    return _CACHE_DIR / f"results_{market}_{date.today().isoformat()}.json"


def _load_cache(market: str) -> dict | None:
    path = _cache_path(market)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save_cache(market: str, state: dict) -> None:
    path = _cache_path(market)
    tmp = path.with_suffix(".tmp")
    payload = {
        "market": market,
        "date": date.today().isoformat(),
        "total": state.get("total", 0),
        "passing": state.get("passing", []),
        "date_range": state.get("date_range", {}),
    }
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# E-3: Control functions
# ---------------------------------------------------------------------------

def _make_initial_state(market: str, total: int) -> dict:
    return {
        "status": "running",
        "market": market,
        "total": total,
        "done": 0,
        "pct": 0.0,
        "date_range": {"start": "", "end": ""},
        "current_price_source": _price_priority_for(market)[0],
        "rate_limited": False,
        "rate_limited_source": None,
        "paused": False,
        "cancelled": False,
        "scanning": [],
        "passing": [],
        "from_cache": False,
        "error": None,
    }


def start_screener(market: str, force: bool = False) -> str:
    """Start a screener job for *market* and return its job_id.

    - If a job for this market is already running/fetching, return the existing job_id.
    - If today's cache exists AND force=False, return a completed job_id immediately.
    - Otherwise start a new background job and return immediately (ticker fetch
      happens inside the thread so the HTTP request doesn't block).
    """
    if market not in _VALID_MARKETS:
        raise ValueError(f"Unknown market: {market!r}")

    # Check for already-running job for this market
    with _STATE_LOCK:
        for jid, state in _SCREENER_STATE.items():
            if state.get("market") == market and state.get("status") in ("running", "fetching_tickers"):
                return jid

    # Check today's disk cache (skip if force=True)
    if not force:
        cached = _load_cache(market)
        if cached:
            job_id = str(uuid.uuid4())
            with _STATE_LOCK:
                _SCREENER_STATE[job_id] = {
                    "status": "done",
                    "market": market,
                    "total": cached.get("total", len(cached.get("passing", []))),
                    "done": cached.get("total", len(cached.get("passing", []))),
                    "pct": 100.0,
                    "date_range": cached.get("date_range", {}),
                    "current_price_source": "cache",
                    "rate_limited": False,
                    "rate_limited_source": None,
                    "paused": False,
                    "cancelled": False,
                    "scanning": [],
                    "passing": cached.get("passing", []),
                    "from_cache": True,
                    "error": None,
                }
            return job_id

    # Return immediately — ticker fetch + scan run entirely inside the daemon thread.
    job_id = str(uuid.uuid4())
    with _STATE_LOCK:
        _SCREENER_STATE[job_id] = {
            **_make_initial_state(market, 0),
            "status": "fetching_tickers",
        }

    t = threading.Thread(target=_run, args=(job_id, market, force), daemon=True)
    t.start()
    return job_id


def pause_screener(job_id: str) -> bool:
    with _STATE_LOCK:
        state = _SCREENER_STATE.get(job_id)
        if state is None or state.get("status") != "running":
            return False
        state["paused"] = True
        state["status"] = "paused"
    return True


def resume_screener(job_id: str) -> bool:
    with _STATE_LOCK:
        state = _SCREENER_STATE.get(job_id)
        if state is None or state.get("status") != "paused":
            return False
        state["paused"] = False
        state["status"] = "running"
    return True


def cancel_screener(job_id: str) -> bool:
    with _STATE_LOCK:
        state = _SCREENER_STATE.get(job_id)
        if state is None:
            return False
        state["cancelled"] = True
        state["paused"] = False  # exit spin-wait
        state["status"] = "cancelled"
    return True


def get_screener_status(job_id: str) -> dict:
    with _STATE_LOCK:
        state = _SCREENER_STATE.get(job_id)
        if state is None:
            return {"status": "not_found"}
        return {
            **{k: v for k, v in state.items() if k not in ("scanning", "passing")},
            "scanning": list(state["scanning"]),
            "passing": list(state["passing"]),
        }


# ---------------------------------------------------------------------------
# E-4: Main batch loop
# ---------------------------------------------------------------------------

def _wait_while_paused(job_id: str) -> bool:
    """Block while job is paused; return False if cancelled during wait."""
    while True:
        with _STATE_LOCK:
            state = _SCREENER_STATE.get(job_id, {})
            if state.get("cancelled"):
                return False
            if not state.get("paused"):
                return True
        time.sleep(0.5)


def _update_date_range(state: dict, data_start: str, data_end: str) -> None:
    """Expand global date range to encompass this ticker's data window."""
    dr = state["date_range"]
    if data_start and (not dr["start"] or data_start < dr["start"]):
        dr["start"] = data_start
    if data_end and (not dr["end"] or data_end > dr["end"]):
        dr["end"] = data_end


def _run(job_id: str, market: str, force: bool) -> None:  # noqa: ARG001
    """Main batch scanning loop executed in a daemon thread."""
    # Step 1: Fetch constituent tickers (moved here so the HTTP request returns fast)
    try:
        if market == MARKET_SP500:
            tickers, _ = get_sp500_tickers()
        elif market == MARKET_NDX:
            tickers, _ = get_nasdaq100_tickers()
        elif market == MARKET_TW50:
            tickers, _ = get_tw50_tickers()
        elif market == MARKET_CN_CSI300:
            tickers, _ = get_cn_csi300_tickers()
        elif market == MARKET_CN_SZ100:
            tickers, _ = get_cn_sz100_tickers()
        elif market == MARKET_CN_GEM:
            tickers, _ = get_cn_gem_tickers()
        elif market == MARKET_CN_STAR:
            tickers, _ = get_cn_star50_tickers()
        else:
            tickers, _ = get_dax40_tickers()
    except Exception as exc:
        with _STATE_LOCK:
            if job_id in _SCREENER_STATE:
                _SCREENER_STATE[job_id]["status"] = "error"
                _SCREENER_STATE[job_id]["error"] = f"Failed to fetch constituent tickers: {exc}"
        return

    with _STATE_LOCK:
        if job_id not in _SCREENER_STATE or _SCREENER_STATE[job_id].get("cancelled"):
            return
        _SCREENER_STATE[job_id]["status"] = "running"
        _SCREENER_STATE[job_id]["total"] = len(tickers)

    priority = _price_priority_for(market)
    batch_size = _batch_size_for(market)
    current_priority = list(priority)  # mutable copy for source switching

    # Resume from last checkpoint (supports pause→resume)
    with _STATE_LOCK:
        start_idx = _SCREENER_STATE[job_id].get("done", 0)

    try:
        for i in range(start_idx, len(tickers)):
            # Pause/cancel check
            if not _wait_while_paused(job_id):
                return  # cancelled

            ticker = tickers[i]
            scan_entry: dict[str, Any] = {"ticker": ticker, "status": "processing"}

            try:
                series, src_used, rl_src = fetch_prices(
                    ticker, market, current_priority
                )

                # Handle rate-limit signal
                if rl_src is not None:
                    with _STATE_LOCK:
                        st = _SCREENER_STATE[job_id]
                        st["rate_limited"] = True
                        st["rate_limited_source"] = rl_src
                    # Remove the rate-limited source from current priority
                    if rl_src in current_priority:
                        current_priority.remove(rl_src)

                if series is not None and getattr(series, "attrs", {}).get("is_suspended"):
                    scan_entry.update({"status": "skipped", "note": "suspended"})
                elif series is None or len(series) < 50:
                    scan_entry.update({"status": "error", "note": "insufficient data"})
                else:
                    metrics = compute_metrics(series)
                    conditions = check_conditions(metrics)

                    with _STATE_LOCK:
                        st = _SCREENER_STATE[job_id]
                        _update_date_range(st, metrics.get("data_start", ""), metrics.get("data_end", ""))

                    if conditions["selected"]:
                        _prc  = round(metrics["price"], 2)   if pd.notna(metrics.get("price",   float("nan"))) else None
                        _w52l = round(metrics["w52_low"], 2) if pd.notna(metrics.get("w52_low", float("nan"))) else None
                        _chg  = round((_prc - _w52l) / _w52l * 100, 1) if (_prc is not None and _w52l is not None and _w52l > 0) else None
                        passing_entry = {
                            "ticker": ticker,
                            "price":   _prc,
                            "change_pct": _chg,
                            "ma50":    round(metrics["ma50"], 2)      if pd.notna(metrics.get("ma50",     float("nan"))) else None,
                            "ma150":   round(metrics["ma150"], 2)     if pd.notna(metrics.get("ma150",    float("nan"))) else None,
                            "ma200":   round(metrics["ma200"], 2)     if pd.notna(metrics.get("ma200",    float("nan"))) else None,
                            "w52_high": round(metrics["w52_high"], 2) if pd.notna(metrics.get("w52_high", float("nan"))) else None,
                            "w52_low":  _w52l,
                            "ma200_1mago": round(metrics["ma200_1mago"], 2) if pd.notna(metrics.get("ma200_1mago", float("nan"))) else None,
                            "above30_low": round(metrics["above30_low"], 2) if pd.notna(metrics.get("above30_low", float("nan"))) else None,
                            "within25_high": round(metrics["within25_high"], 2) if pd.notna(metrics.get("within25_high", float("nan"))) else None,
                            "source": src_used,
                            "name_cn": _get_cn_name(ticker) if market in _CN_MARKETS else (
                                _get_tw_name(ticker) if market == MARKET_TW50 else None
                            ),
                        }
                        with _STATE_LOCK:
                            _SCREENER_STATE[job_id]["passing"].append(passing_entry)
                        scan_entry.update({
                            "status": "pass",
                            "price": _prc,
                            "change_pct": _chg,
                            "source": src_used,
                        })
                    else:
                        scan_entry.update({
                            "status": "fail",
                            "price": round(metrics["price"], 2) if pd.notna(metrics.get("price", float("nan"))) else None,
                            "source": src_used,
                        })

                    if src_used:
                        with _STATE_LOCK:
                            _SCREENER_STATE[job_id]["current_price_source"] = src_used

            except Exception as exc:  # noqa: BLE001
                scan_entry.update({"status": "error", "note": str(exc)[:80]})

            # Update scanning list (keep last 50) and done count
            with _STATE_LOCK:
                st = _SCREENER_STATE[job_id]
                st["scanning"] = (st["scanning"] + [scan_entry])[-50:]
                st["done"] = i + 1
                st["pct"] = round((i + 1) / len(tickers) * 100, 1)

            # Batch boundary: sleep between batches (anti-ban)
            if (i + 1) % batch_size == 0 and (i + 1) < len(tickers):
                # Interruptible sleep: check every 0.5s
                sleep_end = time.monotonic() + random.uniform(3.0, 5.0)
                while time.monotonic() < sleep_end:
                    with _STATE_LOCK:
                        if _SCREENER_STATE[job_id].get("cancelled"):
                            return
                    time.sleep(0.5)

        # Completed normally
        with _STATE_LOCK:
            if not _SCREENER_STATE[job_id].get("cancelled"):
                _SCREENER_STATE[job_id]["status"] = "done"
                _save_cache(market, _SCREENER_STATE[job_id])

    except Exception as exc:  # noqa: BLE001
        with _STATE_LOCK:
            if job_id in _SCREENER_STATE:
                _SCREENER_STATE[job_id]["status"] = "error"
                _SCREENER_STATE[job_id]["error"] = str(exc)


# pandas is used in _run for notna checks
import pandas as pd  # noqa: E402 (keep at bottom to avoid circular)

