from . import stooq, yahoo, twse


def identify_market(symbol: str) -> str:
    """Identify market from symbol.

    Returns: 'tw' if symbol is Taiwan stock, 'us' otherwise
    """
    if symbol.isdigit() or symbol.endswith('.TW') or symbol.endswith('.TWO'):
        return 'tw'
    return 'us'


def get_market_quote(symbol: str, market: str = None) -> dict:
    """Get market quote for stock.

    Args:
        symbol: Stock code (e.g., 'AAPL', '2330', '2330.TW')
        market: Force market ('us' or 'tw'). If None, auto-detect.

    Returns:
        Dict with quote data or error
    """
    if market is None:
        market = identify_market(symbol)

    if market == 'tw':
        return twse.get_quote(symbol)

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


def get_market_history(symbol: str, period: str = "6mo", start=None, end=None, market: str = None) -> dict:
    """Get market history.

    Args:
        symbol: Stock code
        period: Time period (e.g., '6mo', '1y')
        start: Start date (optional)
        end: End date (optional)
        market: Force market ('us' or 'tw'). If None, auto-detect.

    Returns:
        Dict with history data or error
    """
    if market is None:
        market = identify_market(symbol)

    if market == 'tw':
        return twse.get_daily_history(symbol, period=period, start=start, end=end)

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
