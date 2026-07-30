"""Taiwan stock data collection and enrichment service."""
import yfinance as yf
import pandas as pd
import datetime as dt
from typing import Dict, Any, Optional
from data_sources.tw.db import TaiwanStockDB
from data_sources.tw.twse import get_twse_daily, get_twse_pe_ratio


def collect_and_store_tw_stock_data(stock_id: str, db_path: str = 'tw_stock.db',
                                   period: str = '1y') -> Dict[str, Any]:
    """Collect Taiwan stock data via yfinance, enrich with TWSE data, and store in DB.

    Args:
        stock_id: Taiwan stock ID (e.g., '2330' or '2330.TW')
        db_path: Path to SQLite database
        period: yfinance period (default '1y')

    Returns:
        Result dict with status and summary
    """
    try:
        # Normalize ticker
        ticker = stock_id if '.TW' in stock_id else f'{stock_id}.TW'
        symbol_only = stock_id.replace('.TW', '') if '.TW' in stock_id else stock_id

        # Initialize database
        db = TaiwanStockDB(db_path)

        # 1. Fetch historical data via yfinance
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period, auto_adjust=False)

        if hist.empty:
            db.close()
            return {'error': f'No data for {ticker}', 'status': 'failed'}

        # Prepare data for insertion
        hist_reset = hist.reset_index()
        inserted_count = db.insert_daily_prices(symbol_only, hist_reset)

        # 2. Insert company info
        try:
            info = stock.info
            company_name = info.get('shortName', ticker)
            db.insert_company_info(
                symbol_only,
                name=company_name,
                market='TSE'  # Default to TSE for now
            )
        except Exception as e:
            print(f'Warning: Could not fetch company info: {e}')

        # 3. Collect financial metrics from yfinance
        try:
            latest_price = hist_reset.iloc[-1]
            today = dt.date.today().strftime('%Y-%m-%d')

            metrics = {}

            # Try to get basic financials
            try:
                info = stock.info
                metrics['pe_ratio'] = info.get('trailingPE')
                metrics['dividend_yield'] = info.get('dividendYield')
                metrics['market_cap'] = info.get('marketCap')
            except:
                pass

            db.insert_financial_metrics(symbol_only, today, metrics)
        except Exception as e:
            print(f'Warning: Could not insert financial metrics: {e}')

        # 4. Try to enrich with TWSE PE data (latest only)
        try:
            pe_result = get_twse_pe_ratio(symbol_only)
            if 'data' in pe_result and pe_result['data']:
                # Extract PE ratio from TWSE data
                twse_data = pe_result['data']
                if isinstance(twse_data, list) and len(twse_data) > 0:
                    print(f'TWSE PE data: {twse_data[0]}')
        except Exception as e:
            print(f'Warning: Could not fetch TWSE PE data: {e}')

        db.close()

        return {
            'status': 'success',
            'stock_id': symbol_only,
            'ticker': ticker,
            'rows_inserted': inserted_count,
            'period': period
        }

    except Exception as e:
        return {'error': str(e), 'status': 'failed'}


def get_tw_stock_summary(stock_id: str, db_path: str = 'tw_stock.db') -> Dict[str, Any]:
    """Get summary data for a Taiwan stock from database.

    Args:
        stock_id: Taiwan stock ID
        db_path: Path to SQLite database

    Returns:
        Summary dict with price, financials, news
    """
    try:
        symbol_only = stock_id.replace('.TW', '') if '.TW' in stock_id else stock_id
        db = TaiwanStockDB(db_path)

        # Get latest price
        latest_price = db.get_latest_price(symbol_only)

        # Get recent news
        recent_news = db.get_latest_news(symbol_only, limit=5)

        # Get 52-week high/low
        prices = db.get_price_range(symbol_only, days=365)
        high_52 = None
        low_52 = None

        if prices:
            closes = [p['close'] for p in prices if p['close']]
            if closes:
                high_52 = max(closes)
                low_52 = min(closes)

        db.close()

        return {
            'stock_id': symbol_only,
            'current_price': latest_price['close'] if latest_price else None,
            'latest_date': latest_price['date'] if latest_price else None,
            'week_52_high': high_52,
            'week_52_low': low_52,
            'recent_news': recent_news,
            'price_data_points': len(prices)
        }

    except Exception as e:
        return {'error': str(e)}
