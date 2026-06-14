from data_sources.market.service import get_market_quote, get_market_history

_HISTORY_PERIOD = "45d"   # fetch extra calendar days to guarantee ~30 trading days
_SPARKLINE_BARS = 30

# S&P 500, NASDAQ, VIX, TAIEX — 10-Yr Yield excluded per design
DEFAULT_MARKET_CARDS = [
    {"id": "sp500",  "label": "S&P 500", "symbol": "^GSPC"},
    {"id": "nasdaq", "label": "NASDAQ",  "symbol": "^IXIC"},
    {"id": "vix",    "label": "VIX",     "symbol": "^VIX"},
    {"id": "taiex",  "label": "TAIEX",   "symbol": "^TWII", "currency": "TWD"},
]


def build_market_overview(symbols: list[str] | None = None) -> dict:
    cards = []
    symbol_map = {item["symbol"]: item for item in DEFAULT_MARKET_CARDS}
    requested = symbols or [item["symbol"] for item in DEFAULT_MARKET_CARDS]

    for symbol in requested:
        meta = symbol_map.get(symbol, {"id": symbol.lower(), "label": symbol, "symbol": symbol})
        quote = get_market_quote(symbol)
        history = get_market_history(symbol, period=_HISTORY_PERIOD)
        raw_bars = history.get("bars", []) if "error" not in history else []
        sparkline = raw_bars[-_SPARKLINE_BARS:] if len(raw_bars) >= _SPARKLINE_BARS else raw_bars
        cards.append({
            "id": meta["id"],
            "label": meta["label"],
            "symbol": symbol,
            "status": "ok" if "error" not in quote else "unavailable",
            "quote": quote,
            "sparkline_30d": sparkline,
        })

    return {"cards": cards}
