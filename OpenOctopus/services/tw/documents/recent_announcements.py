"""Taiwan stock recent announcements service.

Uses CNYES news API.
"""
from tools.tw_news import get_stock_news


def build_recent_announcements(ticker: str, limit: int = 10) -> dict:
    """Build recent announcements for Taiwan stock.

    Args:
        ticker: Stock code (e.g., '2330')
        limit: Maximum news items

    Returns:
        Dict with news data
    """
    if ticker.endswith('.TW'):
        ticker = ticker[:-3]

    news_data = get_stock_news(ticker, limit=limit)

    if "error" in news_data:
        return {
            "error": news_data.get("error"),
            "ticker": ticker,
            "announcements": []
        }

    return {
        "ticker": ticker,
        "announcements": news_data.get("news", []),
        "total_count": news_data.get("news_count", 0),
        "source": "CNYES",
        "note": "News from CNYES; for official announcements, check TWSE website"
    }
