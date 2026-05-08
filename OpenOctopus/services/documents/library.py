"""Document Library service.

Scans the local HF transcript cache (.cache/hf_transcripts/) and returns
a flat list of all cached transcript entries, suitable for the Documents
Library tab in the frontend.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from data_sources.transcripts.hf_downloader import CACHE_DIR


def build_document_library() -> dict:
    """Return all locally cached transcript entries, sorted by ticker."""
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
        excerpt = _read_excerpt(jsonl_path, offset) if offset is not None else None
        result.append({
            "ticker": (e.get("symbol") or ticker).upper(),
            "doc_type": "Earnings Transcript",
            "type_key": "transcript",
            "period": period,
            "year": year,
            "quarter": quarter,
            "filed_date": filed_date,
            "company_name": e.get("company_name") or "",
            "excerpt": excerpt or "",
            "source": "hf_cached_transcripts",
        })
    return result


def _scan_jsonl(jsonl_path: Path, ticker: str) -> list[dict]:
    """Build entries by scanning JSONL line by line (no idx.json available)."""
    entries = []
    _re_str = re.compile(r'"(\w+)"\s*:\s*"([^"]*)"')
    _re_int = re.compile(r'"(\w+)"\s*:\s*(\d+)')

    try:
        with jsonl_path.open("rb") as fh:
            while True:
                offset = fh.tell()
                raw_line = fh.readline()
                if not raw_line:
                    break
                snippet = raw_line[:500].decode("utf-8", errors="replace")

                def _str(key):
                    m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', snippet)
                    return m.group(1) if m else None

                def _int(key):
                    m = re.search(rf'"{key}"\s*:\s*(\d+)', snippet)
                    return int(m.group(1)) if m else None

                sym = (_str("symbol") or ticker).upper()
                year = _int("year")
                quarter = _int("quarter")
                date_raw = _str("date") or ""
                filed_date = date_raw[:10] if date_raw else None
                period = f"Q{quarter} {year}" if year and quarter else "N/A"
                excerpt = _read_excerpt(jsonl_path, offset)
                entries.append({
                    "ticker": sym,
                    "doc_type": "Earnings Transcript",
                    "type_key": "transcript",
                    "period": period,
                    "year": year,
                    "quarter": quarter,
                    "filed_date": filed_date,
                    "company_name": "",
                    "excerpt": excerpt or "",
                    "source": "hf_cached_transcripts",
                })
    except OSError:
        pass
    return entries


def _read_excerpt(jsonl_path: Path, offset: int, max_chars: int = 250) -> str | None:
    """Read and return the first max_chars of content from a JSONL record by byte offset."""
    if not jsonl_path.exists():
        return None
    try:
        with jsonl_path.open("rb") as fh:
            fh.seek(offset)
            line = fh.readline().decode("utf-8", errors="replace").strip()
            if not line:
                return None
            record = json.loads(line)
            content = record.get("content") or ""
            return content[:max_chars].strip() or None
    except (OSError, json.JSONDecodeError):
        return None
