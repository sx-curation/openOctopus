from data_sources.market.service import get_market_quote, get_market_history

_HISTORY_PERIOD = "45d"   # enough calendar days for ~30 trading bars
_SPARKLINE_BARS = 30

COMMODITY_CARDS = [
    {"id": "brent", "label": "Brent Crude", "symbol": "BZ=F", "unit": "USD/bbl"},
    {"id": "gold",  "label": "Gold",        "symbol": "GC=F", "unit": "USD/oz"},
]


def build_market_commodities() -> dict:
    cards = []
    for meta in COMMODITY_CARDS:
        symbol = meta["symbol"]
        quote = get_market_quote(symbol)
        history = get_market_history(symbol, period=_HISTORY_PERIOD)
        raw_bars = history.get("bars", []) if "error" not in history else []
        sparkline = raw_bars[-_SPARKLINE_BARS:] if len(raw_bars) >= _SPARKLINE_BARS else raw_bars

        cards.append({
            "id": meta["id"],
            "label": meta["label"],
            "symbol": symbol,
            "unit": meta["unit"],
            "status": "ok" if "error" not in quote else "unavailable",
            "quote": quote,
            "sparkline_30d": sparkline,
        })

    return {"cards": cards}
