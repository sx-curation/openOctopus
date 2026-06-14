"""Backlog ticker search service.

Supports two modes:
1. Direct ticker validation: if query looks like a ticker (all-caps letters/numbers/dots)
2. Company name fuzzy search: uses yfinance.Search for name-based lookup
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

_TICKER_PATTERN = re.compile(r'^[A-Z0-9.\-]{1,10}$')


def _normalize_symbol(symbol: str) -> str:
    """Convert Yahoo Finance A-share symbols to internal format.

    Yahoo Finance uses .SS for Shanghai; we use .SH internally.
      600176.SS → 600176.SH
      000858.SZ → 000858.SZ  (unchanged)
    """
    s = symbol.upper()
    if s.endswith(".SS"):
        return s[:-3] + ".SH"
    return s


def search_ticker(query: str) -> list[dict]:
    """Search for tickers by symbol or company name.

    Returns a list of up to 5 dicts with keys: symbol, name, exchange.
    Returns [] on failure or no results.
    """
    import yfinance as yf  # lazy import

    q = query.strip()
    if not q:
        return []

    q_upper = q.upper()

    # Mode 1: looks like a ticker — validate directly
    if _TICKER_PATTERN.match(q_upper):
        try:
            info = yf.Ticker(q_upper).info or {}
            quote_type = info.get("quoteType")
            if quote_type:
                return [{
                    "symbol": _normalize_symbol(q_upper),
                    "name": info.get("shortName") or info.get("longName") or q_upper,
                    "exchange": info.get("exchange") or "",
                }]
        except Exception as e:
            logger.debug("backlog search: direct ticker check failed for %s: %s", q_upper, e)

    # Mode 2: company name search
    try:
        search = yf.Search(q, max_results=10)
        quotes = search.quotes or []
        results = []
        for item in quotes:
            if item.get("quoteType") != "EQUITY":
                continue
            symbol = item.get("symbol") or ""
            if not symbol:
                continue
            results.append({
                "symbol": _normalize_symbol(symbol),
                "name": item.get("longname") or item.get("shortname") or symbol,
                "exchange": item.get("exchange") or "",
            })
            if len(results) >= 5:
                break
        return results
    except Exception as e:
        logger.warning("backlog search: yf.Search failed for %r: %s", q, e)
        return []
