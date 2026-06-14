"""Taiwan Stock Exchange (TWSE) data sources via official API.

References: Colab CH-03 第 26-66 行
"""
import requests
import pandas as pd
import datetime as dt
from dateutil.relativedelta import relativedelta
from typing import Dict, List, Any


def get_daily_trading(symbol: str, date: str = None) -> Dict[str, Any]:
    """Get daily trading info from TWSE.

    Args:
        symbol: Stock code (e.g., '2330' for TSMC)
        date: Date string (YYYYMMDD). Defaults to today.

    Returns:
        Dict with fields/data or error
    """
    if date is None:
        date = dt.date.today().strftime("%Y%m%d")

    try:
        url = f'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={date}&stockNo={symbol}'
        response = requests.get(url, timeout=10, verify=False)
        response.raise_for_status()
        json_data = response.json()

        if 'data' in json_data and json_data['data']:
            df = pd.DataFrame(data=json_data['data'], columns=json_data['fields'])
            return {
                "symbol": symbol,
                "date": date,
                "data": df.to_dict('records'),
                "fields": json_data['fields']
            }
        else:
            return {"error": f"No data for {symbol} on {date}", "symbol": symbol}

    except Exception as e:
        return {"error": str(e), "symbol": symbol}


def get_pe_ratio_monthly(symbol: str, months: int = 3) -> Dict[str, Any]:
    """Get monthly PE ratio and related indicators from TWSE.

    Args:
        symbol: Stock code (e.g., '2330')
        months: Number of months to fetch (default 3)

    Returns:
        Dict with aggregated monthly data
    """
    date_now = dt.datetime.now()
    date_list = [
        (date_now - relativedelta(months=i)).replace(day=1).strftime('%Y%m%d')
        for i in range(months)
    ]
    date_list.reverse()
    all_df = pd.DataFrame()

    for date in date_list:
        try:
            url = f'https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU?date={date}&stockNo={symbol}'
            response = requests.get(url, timeout=10, verify=False)
            response.raise_for_status()
            json_data = response.json()

            if 'data' in json_data and json_data['data']:
                df = pd.DataFrame(data=json_data['data'], columns=json_data['fields'])
                all_df = pd.concat([all_df, df], ignore_index=True)
        except Exception as e:
            pass

    if not all_df.empty:
        return {
            "symbol": symbol,
            "months": months,
            "data": all_df.to_dict('records'),
            "fields": list(all_df.columns)
        }
    else:
        return {"error": f"No PE ratio data for {symbol}", "symbol": symbol}


def get_quote(symbol: str) -> Dict[str, Any]:
    """Get current quote for Taiwan stock.

    Args:
        symbol: Stock code (e.g., '2330')

    Returns:
        Dict with latest trading info or error
    """
    today = dt.date.today().strftime("%Y%m%d")
    result = get_daily_trading(symbol, today)

    if "error" in result:
        # Try yesterday if today has no data
        yesterday = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y%m%d")
        result = get_daily_trading(symbol, yesterday)

    return result


def get_daily_history(symbol: str, period: str = "6mo", start=None, end=None) -> Dict[str, Any]:
    """Get daily history (currently uses get_pe_ratio_monthly as placeholder).

    Note: For full daily OHLCV data, recommend using yfinance instead.
    This is a wrapper for TWSE's available APIs.

    Args:
        symbol: Stock code (e.g., '2330')
        period: Period (e.g., '6mo', '1y')
        start: Start date (optional)
        end: End date (optional)

    Returns:
        Dict with monthly data
    """
    # Parse period to months
    if period == "6mo":
        months = 6
    elif period == "1y":
        months = 12
    elif period == "3mo":
        months = 3
    else:
        months = 3

    return get_pe_ratio_monthly(symbol, months=months)


def get_analyst_snapshot(symbol: str) -> Dict[str, Any]:
    """Get analyst info (placeholder - TWSE doesn't provide this directly).

    Returns:
        Error indicating this data source is not available for TWSE
    """
    return {"error": "analyst_data_not_available_from_twse", "symbol": symbol}
