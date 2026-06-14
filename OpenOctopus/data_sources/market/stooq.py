import csv
from io import StringIO

import requests


_SYMBOL_MAP = {
    "^GSPC": "^spx",
    "^IXIC": "^ndq",
    "^VIX": "^vix",
    "^TNX": "10us",
}


def normalize_symbol(symbol: str) -> str:
    upper = symbol.upper()
    if upper in _SYMBOL_MAP:
        return _SYMBOL_MAP[upper]
    if upper.startswith("^"):
        return upper.lower()
    if "." in upper:
        return upper.lower()
    return f"{upper.lower()}.us"


def get_quote(symbol: str, timeout: int = 15) -> dict:
    normalized = normalize_symbol(symbol)
    url = f"https://stooq.com/q/l/?s={normalized}&f=sd2t2ohlcvn&e=csv"

    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        rows = list(csv.reader(StringIO(response.text.strip())))
        if not rows or len(rows[0]) < 8:
            return {"error": "invalid_csv_payload", "symbol": symbol.upper(), "source": "stooq"}

        row = rows[0]
        if row[0].startswith("Get your apikey"):
            return {"error": "quote_requires_apikey", "symbol": symbol.upper(), "source": "stooq"}

        volume = row[7]
        return {
            "symbol": symbol.upper(),
            "source": "stooq",
            "provider_symbol": normalized,
            "price": _to_float(row[6]) if len(row) > 6 else None,
            "change_pct": None,
            "open": _to_float(row[3]),
            "high": _to_float(row[4]),
            "low": _to_float(row[5]),
            "close": _to_float(row[6]) if len(row) > 6 else None,
            "volume": int(volume) if volume.isdigit() else None,
            "currency": None,
            "as_of": row[1] if len(row) > 1 else None,
            "name": row[8] if len(row) > 8 else None,
        }
    except Exception as exc:
        return {"error": str(exc), "symbol": symbol.upper(), "source": "stooq"}


def get_daily_history(symbol: str, start=None, end=None, period: str = "6mo") -> dict:
    return {
        "error": "history_requires_stooq_apikey",
        "symbol": symbol.upper(),
        "source": "stooq",
        "start": str(start) if start else None,
        "end": str(end) if end else None,
        "period": period,
        "detail": (
            "Anonymous Stooq access in this environment supports quote snapshots, "
            "but the daily-history endpoint returns an apikey gate."
        ),
    }


def _to_float(value: str) -> float | None:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None
