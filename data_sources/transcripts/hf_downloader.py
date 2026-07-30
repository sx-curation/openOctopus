"""
hf_downloader.py — Background per-ticker transcript downloader.

Downloads earnings transcripts from HuggingFace (kurry/sp500_earnings_transcripts)
into per-ticker JSONL files at .cache/hf_transcripts/{TICKER}.jsonl.

Key design:
- DuckDB HTTPFS scans both parquet shards (shard0 ~1.79 GB / ~7 min, shard1 ~33 MB)
- Downloads run in daemon threads via AsyncRunner so Flask never blocks
- Manifest tracks which tickers have been downloaded and their year coverage
- Atomic manifest writes (`.tmp` → `os.replace`) prevent corruption on concurrent writes

Usage
-----
from data_sources.transcripts.hf_downloader import (
    trigger_background_download,
    get_download_status,
    ticker_jsonl_path,
    CACHE_DIR,
)

triggered = trigger_background_download("AAPL")  # → True if new download started
status    = get_download_status("AAPL")           # → {status, message, years}
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CACHE_DIR = Path(".cache/hf_transcripts")
MANIFEST_PATH = CACHE_DIR / "download_manifest.json"

# Two parquet shards from kurry/sp500_earnings_transcripts.
# AAPL and most S&P 500 tickers are in shard0 (~1.79 GB, ~7 min scan).
# Shard1 is ~33 MB and covers ~53 tickers.
# Both shards are always queried so we never miss a ticker.
_DEFAULT_SHARD_URLS = [
    "https://huggingface.co/api/datasets/kurry/sp500_earnings_transcripts/parquet/default/train/0.parquet",
    "https://huggingface.co/api/datasets/kurry/sp500_earnings_transcripts/parquet/default/train/1.parquet",
]

def _shard_urls() -> list[str]:
    """Return shard URLs — overridable via HF_EARNINGS_SHARD_URLS env var (comma-separated)."""
    env_val = os.getenv("HF_EARNINGS_SHARD_URLS", "")
    if env_val.strip():
        return [u.strip() for u in env_val.split(",") if u.strip()]
    return _DEFAULT_SHARD_URLS


# ---------------------------------------------------------------------------
# Manifest helpers  (thread-safe via _manifest_lock)
# ---------------------------------------------------------------------------

_manifest_lock = threading.Lock()


def ticker_jsonl_path(ticker: str) -> Path:
    """Return the per-ticker JSONL path for *ticker*."""
    return CACHE_DIR / f"{ticker.upper()}.jsonl"


def _read_manifest() -> dict:
    """Read download_manifest.json; return {} if missing or corrupt."""
    with _manifest_lock:
        if not MANIFEST_PATH.exists():
            return {}
        try:
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}


def _write_manifest(manifest: dict) -> None:
    """Atomically overwrite the manifest file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(CACHE_DIR), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, str(MANIFEST_PATH))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Cache freshness check
# ---------------------------------------------------------------------------

def _needs_download(ticker: str) -> bool:
    """Return True if *ticker* data is absent or lacks current/prior year coverage."""
    ticker = ticker.upper()
    # If the JSONL file doesn't exist, we definitely need a download
    if not ticker_jsonl_path(ticker).exists():
        return True
    manifest = _read_manifest()
    entry = manifest.get(ticker)
    if not entry:
        return True
    years: list[int] = entry.get("years", [])
    current_year = datetime.now().year
    return current_year not in years and (current_year - 1) not in years


# ---------------------------------------------------------------------------
# Core download (runs in daemon thread — can take ~7 min for shard0)
# ---------------------------------------------------------------------------

def _download_ticker(ticker: str) -> dict[str, Any]:
    """Download all transcripts for *ticker* from HuggingFace and write JSONL.

    Runs entirely inside an AsyncRunner daemon thread.
    Returns a summary dict stored as the job result.
    """
    ticker = ticker.upper()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ticker_jsonl_path(ticker)
    shard_urls = _shard_urls()

    logger.info("hf_downloader: starting download for %s (shards: %s)", ticker, shard_urls)

    try:
        import duckdb
    except ImportError:
        raise RuntimeError("duckdb not installed — run: pip install duckdb>=0.10.0")

    conn = duckdb.connect()
    # Install / load httpfs extension for remote parquet access
    conn.execute("INSTALL httpfs; LOAD httpfs;")

    shard_list = ", ".join(f"'{u}'" for u in shard_urls)
    query = f"""
        SELECT
            symbol,
            year,
            quarter,
            date,
            content,
            structured_content,
            company_name
        FROM parquet_scan([{shard_list}])
        WHERE symbol = '{ticker}'
    """
    logger.info("hf_downloader: running DuckDB scan for %s (may take ~7 min for shard0)", ticker)
    rows = conn.execute(query).fetchall()
    conn.close()

    if not rows:
        logger.warning("hf_downloader: no rows found for %s", ticker)
        return {"ticker": ticker, "rows_written": 0, "years": []}

    years: set[int] = set()
    rows_written = 0

    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            symbol, year, quarter, date, content, structured_content, company_name = row
            # Skip records older than 5 years
            if year is not None and int(year) < datetime.now().year - 5:
                continue
            record = {
                "symbol": str(symbol) if symbol is not None else ticker,
                "year": int(year) if year is not None else None,
                "quarter": int(quarter) if quarter is not None else None,
                "date": str(date) if date is not None else None,
                "content": str(content) if content is not None else "",
                "structured_content": (
                    structured_content if isinstance(structured_content, list) else []
                ),
                "company_name": str(company_name) if company_name is not None else "",
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            rows_written += 1
            if year is not None:
                years.add(int(year))

    # Update manifest
    with _manifest_lock:
        manifest = _read_manifest()
        manifest[ticker] = {
            "years": sorted(years),
            "rows": rows_written,
            "downloaded_at": datetime.now().isoformat(),
        }
        _write_manifest(manifest)

    logger.info(
        "hf_downloader: wrote %d rows for %s (years: %s)",
        rows_written, ticker, sorted(years),
    )
    return {"ticker": ticker, "rows_written": rows_written, "years": sorted(years)}


# ---------------------------------------------------------------------------
# Public trigger / status API
# ---------------------------------------------------------------------------

def trigger_background_download(ticker: str) -> bool:
    """Trigger a background download for *ticker* if one is not already running.

    Returns True if a new download was started, False if skipped
    (already running, or manifest says data is fresh).
    """
    from utils.async_runner import submit, is_running

    ticker = ticker.upper()

    # Don't re-trigger if a job is already running for this ticker
    if is_running(ticker):
        return False

    if not _needs_download(ticker):
        return False

    submit(_download_ticker, ticker, job_id=ticker)
    logger.info("hf_downloader: triggered background download for %s", ticker)
    return True


def get_download_status(ticker: str) -> dict:
    """Return the current download status for *ticker*.

    Format: {status: running|done|error|not_found, message, years: [...]}
    """
    from utils.async_runner import get_status

    ticker = ticker.upper()
    status = get_status(ticker)
    manifest = _read_manifest()
    years = manifest.get(ticker, {}).get("years", [])
    return {**status, "ticker": ticker, "years": years}
