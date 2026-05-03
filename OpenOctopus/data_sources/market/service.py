from . import stooq, yahoo


def get_market_quote(symbol: str) -> dict:
    primary = yahoo.get_quote(symbol)
    if "error" not in primary:
        return primary

    fallback = stooq.get_quote(symbol)
    if "error" not in fallback:
        fallback["fallback_reason"] = primary["error"]
        return fallback

    return {
        "error": "all_market_quote_providers_failed",
        "symbol": symbol.upper(),
        "providers": {
            "yahoo": primary,
            "stooq": fallback,
        },
    }


def get_market_history(symbol: str, period: str = "6mo", start=None, end=None) -> dict:
    primary = yahoo.get_daily_history(symbol, period=period, start=start, end=end)
    if "error" not in primary:
        return primary

    fallback = stooq.get_daily_history(symbol, period=period, start=start, end=end)
    if "error" not in fallback:
        fallback["fallback_reason"] = primary["error"]
        return fallback

    return {
        "error": "all_market_history_providers_failed",
        "symbol": symbol.upper(),
        "providers": {
            "yahoo": primary,
            "stooq": fallback,
        },
    }


def get_market_analyst_snapshot(symbol: str) -> dict:
    analyst = yahoo.get_analyst_snapshot(symbol)
    if "error" not in analyst:
        return analyst

    return {
        "error": "all_market_analyst_providers_failed",
        "symbol": symbol.upper(),
        "providers": {
            "yahoo": analyst,
        },
    }
