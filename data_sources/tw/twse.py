"""Taiwan Stock Exchange (TWSE) API data collector."""
import requests
import pandas as pd
import datetime as dt
from dateutil.relativedelta import relativedelta
from typing import Dict, Any, Optional


def get_twse_daily(stock_id: str, date: Optional[str] = None) -> Dict[str, Any]:
    """Get daily trading data from TWSE API for a single stock.

    Args:
        stock_id: Taiwan stock ID (e.g., '2330')
        date: Date in YYYYMMDD format. If None, uses today.

    Returns:
        DataFrame with daily trading data or error dict
    """
    try:
        if not date:
            date = dt.date.today().strftime("%Y%m%d")

        url = f'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={date}&stockNo={stock_id}'
        response = requests.get(url, timeout=10)
        json_data = response.json()

        if 'data' not in json_data or not json_data['data']:
            return {'error': f'No data for {stock_id} on {date}'}

        df = pd.DataFrame(data=json_data['data'], columns=json_data['fields'])
        return {'data': df.to_dict('records'), 'status': 'ok'}
    except Exception as e:
        return {'error': f'TWSE API error: {str(e)}'}


def get_twse_pe_ratio(stock_id: str, date: Optional[str] = None) -> Dict[str, Any]:
    """Get PE ratio and other indicators from TWSE API.

    Args:
        stock_id: Taiwan stock ID (e.g., '2330')
        date: Date in YYYYMMDD format. If None, uses today.

    Returns:
        DataFrame with PE ratios or error dict
    """
    try:
        if not date:
            date = dt.date.today().strftime("%Y%m%d")

        url = f'https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU?date={date}&stockNo={stock_id}'
        response = requests.get(url, timeout=10)
        json_data = response.json()

        if 'data' not in json_data or not json_data['data']:
            return {'error': f'No PE data for {stock_id} on {date}'}

        df = pd.DataFrame(data=json_data['data'], columns=json_data['fields'])
        return {'data': df.to_dict('records'), 'status': 'ok'}
    except Exception as e:
        return {'error': f'TWSE PE API error: {str(e)}'}


def get_twse_history(stock_id: str, months: int = 3) -> Dict[str, Any]:
    """Get PE ratio history for multiple months.

    Args:
        stock_id: Taiwan stock ID (e.g., '2330')
        months: Number of months to fetch

    Returns:
        Combined DataFrame or error dict
    """
    try:
        date_now = dt.datetime.now()
        date_list = [
            (date_now - relativedelta(months=i)).replace(day=1).strftime('%Y%m%d')
            for i in range(months)
        ]
        date_list.reverse()

        all_df = pd.DataFrame()

        for date in date_list:
            try:
                url = f'https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU?date={date}&stockNo={stock_id}'
                json_data = requests.get(url, timeout=10).json()

                if 'data' in json_data and json_data['data']:
                    df = pd.DataFrame(data=json_data['data'], columns=json_data['fields'])
                    all_df = pd.concat([all_df, df], ignore_index=True)
            except Exception:
                pass  # Skip individual month errors

        if all_df.empty:
            return {'error': f'No history data for {stock_id}'}

        return {'data': all_df.to_dict('records'), 'status': 'ok'}
    except Exception as e:
        return {'error': f'TWSE history error: {str(e)}'}
