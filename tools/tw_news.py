"""Taiwan stock news from CNYES API.

Reference: Colab CH-03 第 171-194 行
"""
import requests
from datetime import datetime
from typing import Dict, List, Any


def get_stock_news(ticker: str, limit: int = 10) -> Dict[str, Any]:
    """Get latest news for Taiwan stock from CNYES API.

    Args:
        ticker: Stock code (e.g., '2330' - no .TW suffix needed)
        limit: Maximum number of news items (default 10)

    Returns:
        Dict with news data or error
    """
    # Remove .TW suffix if present for API call
    if ticker.endswith('.TW'):
        ticker = ticker[:-3]

    try:
        url = f'https://ess.api.cnyes.com/ess/api/v1/news/keyword?q={ticker}&limit={limit}&page=1'
        response = requests.get(url, timeout=10, verify=False)
        response.raise_for_status()
        json_data = response.json()

        if 'data' not in json_data or 'items' not in json_data['data']:
            return {"error": "no_news_data", "ticker": ticker}

        items = json_data['data']['items']
        news_list = []

        for item in items:
            try:
                news_id = item.get("newsId")
                title = item.get("title")
                publish_at = item.get("publishAt")

                # Convert UTC timestamp to date
                if publish_at:
                    utc_time = datetime.utcfromtimestamp(publish_at)
                    formatted_date = utc_time.strftime('%Y-%m-%d')
                else:
                    formatted_date = None

                news_list.append({
                    "stock": ticker,
                    "date": formatted_date,
                    "title": title,
                    "news_id": news_id,
                    "url": f"https://news.cnyes.com/news/id/{news_id}" if news_id else None
                })
            except Exception:
                continue

        return {
            "ticker": ticker,
            "news_count": len(news_list),
            "news": news_list,
            "source": "CNYES"
        }

    except Exception as e:
        return {"error": str(e), "ticker": ticker}
