import json
import re
from datetime import datetime, timezone
from pathlib import Path

from config import settings


# Lightweight index: (symbol, year, quarter) → {date, company_name, byte_offset}
_OFFSET_INDEX: dict[tuple[str, float], dict] = {}


def get_cached_transcript(ticker: str, year: int | None = None, quarter: int | None = None) -> dict:
    ticker = ticker.upper()
    path = Path(settings.HF_TRANSCRIPTS_PATH)
    if not path.exists():
        return {
            "error": "transcript_cache_missing",
            "ticker": ticker,
            "path": str(path),
        }

    index = _load_offset_index(path)
    if year is not None and quarter is not None:
        meta = index.get((ticker, year, quarter))
    else:
        matching = [(key, m) for key, m in index.items() if key[0] == ticker]
        meta = _select_nearest_meta(matching)

    if not meta:
        return {
            "error": "transcript_not_found",
            "ticker": ticker,
            "year": year,
            "quarter": quarter,
            "path": str(path),
        }

    record = _read_record_at_offset(path, meta["offset"])
    if record is None:
        return {"error": "transcript_read_error", "ticker": ticker}

    structured = record.get("structured_content") or []
    if not isinstance(structured, list):
        structured = []

    return {
        "ticker": ticker,
        "year": record.get("year"),
        "quarter": record.get("quarter"),
        "date": record.get("date"),
        "company_name": record.get("company_name"),
        "source": "hf_cached_transcripts",
        "cache_path": str(path),
        "content_excerpt": (record.get("content") or "")[: settings.TRANSCRIPT_MAX_CHARS],
        "content_chars": len(record.get("content") or ""),
        "structured_excerpt": structured[:8],
        "structured_count": len(structured),
    }


def _load_offset_index(path: Path) -> dict:
    """Build a lightweight index storing only metadata + byte offsets (not content)."""
    cache_key = (str(path.resolve()), path.stat().st_mtime)
    cached = _OFFSET_INDEX.get(cache_key)
    if cached is not None:
        return cached

    idx_path = path.with_suffix(".idx.json")
    mtime = path.stat().st_mtime
    if idx_path.exists():
        try:
            raw = json.loads(idx_path.read_text(encoding="utf-8"))
            if raw.get("mtime") == mtime:
                index = {
                    (e["symbol"], e["year"], e["quarter"]): {
                        "date": e.get("date"),
                        "company_name": e.get("company_name"),
                        "offset": e["offset"],
                    }
                    for e in raw["entries"]
                }
                _OFFSET_INDEX.clear()
                _OFFSET_INDEX[cache_key] = index
                return index
        except (json.JSONDecodeError, KeyError):
            pass

    index: dict[tuple[str, int, int], dict] = {}
    entries = []
    with path.open("rb") as handle:
        while True:
            offset = handle.tell()
            raw_line = handle.readline()
            if not raw_line:
                break
            # Extract header fields via regex on first ~500 bytes (avoids full JSON parse)
            snippet = raw_line[:500].decode("utf-8", errors="replace")
            symbol = _extract_json_str(snippet, "symbol")
            year = _extract_json_int(snippet, "year")
            quarter = _extract_json_int(snippet, "quarter")
            if not symbol or year is None or quarter is None:
                continue
            symbol = symbol.upper()
            date_val = _extract_json_str(snippet, "date")
            company_name = _extract_json_str(snippet, "company_name")
            meta = {"date": date_val, "company_name": company_name, "offset": offset}
            index[(symbol, int(year), int(quarter))] = meta
            entries.append({
                "symbol": symbol,
                "year": int(year),
                "quarter": int(quarter),
                "date": date_val,
                "company_name": company_name,
                "offset": offset,
            })

    try:
        idx_path.write_text(
            json.dumps({"mtime": mtime, "entries": entries}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass

    _OFFSET_INDEX.clear()
    _OFFSET_INDEX[cache_key] = index
    return index


def _read_record_at_offset(path: Path, offset: int) -> dict | None:
    """Read a single JSONL record by seeking to its byte offset."""
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            line = handle.readline().decode("utf-8", errors="replace").strip()
            if line:
                return json.loads(line)
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _select_nearest_meta(entries: list[tuple[tuple, dict]]) -> dict | None:
    """Pick the metadata entry whose date is closest to now."""
    if not entries:
        return None
    now = _current_utc()
    dated = []
    undated = []
    for (sym, yr, qtr), meta in entries:
        parsed = _parse_transcript_datetime(meta.get("date"))
        if parsed is None:
            undated.append((yr, qtr, meta))
            continue
        dated.append((abs((parsed - now).total_seconds()), parsed <= now, parsed, meta))
    if dated:
        dated.sort(key=lambda x: (x[0], not x[1], -x[2].timestamp()))
        return dated[0][3]
    undated.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return undated[0][2] if undated else None



def _parse_transcript_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace(" UTC", "+00:00").replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(normalized, fmt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _current_utc() -> datetime:
    return datetime.now(timezone.utc)


def _extract_json_str(snippet: str, key: str) -> str | None:
    m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', snippet)
    return m.group(1) if m else None


def _extract_json_int(snippet: str, key: str) -> int | None:
    m = re.search(rf'"{key}"\s*:\s*(\d+)', snippet)
    return int(m.group(1)) if m else None
