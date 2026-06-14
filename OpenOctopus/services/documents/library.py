"""Document Library service.

Scans the local HF transcript cache (.cache/hf_transcripts/) and returns
a flat list of all cached transcript entries, suitable for the Documents
Library tab in the frontend.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from data_sources.transcripts.hf_downloader import CACHE_DIR

_FIVE_YEARS_AGO = (datetime.now() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")


def build_document_library() -> dict:
    """Return locally cached transcript entries from the last 5 years, sorted by ticker."""
    entries: list[dict] = []

    if not CACHE_DIR.exists():
        return {"items": [], "total": 0, "source": "hf_transcripts"}

    # Collect all tickers from both .idx.json and .jsonl files
    all_tickers: set[str] = set()
    for p in CACHE_DIR.iterdir():
        if p.suffix == '.jsonl':
            all_tickers.add(p.stem.upper())
        elif p.name.endswith('.idx.json'):
            ticker = p.name.replace('.idx.json', '').upper()
            all_tickers.add(ticker)

    for ticker in sorted(all_tickers):
        idx_path = CACHE_DIR / f"{ticker}.idx.json"
        jsonl_path = CACHE_DIR / f"{ticker}.jsonl"

        if idx_path.exists():
            # Fast path: use pre-built index
            try:
                raw = json.loads(idx_path.read_text(encoding="utf-8"))
                for e in raw.get("entries", []):
                    entries.extend(_make_entries_from_idx([e], jsonl_path, ticker))
            except (OSError, json.JSONDecodeError):
                pass
        elif jsonl_path.exists():
            # Slow path: scan JSONL directly (no index file)
            entries.extend(_scan_jsonl(jsonl_path, ticker))

    # Filter to last 5 years only
    entries = [e for e in entries if (e.get("filed_date") or "") >= _FIVE_YEARS_AGO]

    entries.sort(key=lambda x: (x["ticker"], -(x["year"] or 0), -(x["quarter"] or 0)))

    return {"items": entries, "total": len(entries), "source": "hf_transcripts"}


def _make_entries_from_idx(idx_entries: list[dict], jsonl_path: Path, ticker: str) -> list[dict]:
    result = []
    for e in idx_entries:
        year = e.get("year")
        quarter = e.get("quarter")
        date_raw = e.get("date") or ""
        filed_date = date_raw[:10] if date_raw else None
        period = f"Q{quarter} {year}" if year and quarter else "N/A"
        offset = e.get("offset")
        info = _read_content_info(jsonl_path, offset) if offset is not None else {"excerpt": "", "char_count": 0}
        result.append({
            "ticker": (e.get("symbol") or ticker).upper(),
            "doc_type": "Earnings Transcript",
            "type_key": "transcript",
            "period": period,
            "year": year,
            "quarter": quarter,
            "filed_date": filed_date,
            "company_name": e.get("company_name") or "",
            "excerpt": info["excerpt"],
            "char_count": info["char_count"],
            "source": "hf_cached_transcripts",
        })
    return result


def _scan_jsonl(jsonl_path: Path, ticker: str) -> list[dict]:
    """Build entries by scanning JSONL line by line (no idx.json available)."""
    entries = []

    try:
        with jsonl_path.open("rb") as fh:
            while True:
                raw_line = fh.readline()
                if not raw_line:
                    break
                try:
                    record = json.loads(raw_line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue

                sym = (record.get("symbol") or ticker).upper()
                year = record.get("year")
                quarter = record.get("quarter")
                date_raw = str(record.get("date") or "")
                filed_date = date_raw[:10] if date_raw else None
                period = f"Q{quarter} {year}" if year and quarter else "N/A"
                content = record.get("content") or ""
                entries.append({
                    "ticker": sym,
                    "doc_type": "Earnings Transcript",
                    "type_key": "transcript",
                    "period": period,
                    "year": int(year) if year is not None else None,
                    "quarter": int(quarter) if quarter is not None else None,
                    "filed_date": filed_date,
                    "company_name": record.get("company_name") or "",
                    "excerpt": content[:200].strip(),
                    "char_count": len(content),
                    "source": "hf_cached_transcripts",
                })
    except OSError:
        pass
    return entries


def _read_content_info(jsonl_path: Path, offset: int) -> dict:
    """Read content excerpt (200 chars) and total char count from a JSONL record by byte offset."""
    if not jsonl_path.exists():
        return {"excerpt": "", "char_count": 0}
    try:
        with jsonl_path.open("rb") as fh:
            fh.seek(offset)
            line = fh.readline().decode("utf-8", errors="replace").strip()
            if not line:
                return {"excerpt": "", "char_count": 0}
            record = json.loads(line)
            content = record.get("content") or ""
            return {"excerpt": content[:200].strip(), "char_count": len(content)}
    except (OSError, json.JSONDecodeError):
        return {"excerpt": "", "char_count": 0}

