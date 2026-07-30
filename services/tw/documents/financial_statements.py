"""Taiwan stock financial statements service."""
import yfinance as yf
from typing import Dict, Any, Optional


def build_financial_statements(ticker: str) -> Dict[str, Any]:
    """Build Taiwan stock financial statements (年報/季報) from yfinance.

    Args:
        ticker: Taiwan stock code (e.g., '2330')

    Returns:
        Dict with financial statements data
    """
    try:
        # Normalize ticker
        ticker_clean = ticker.replace('.TW', '') if '.TW' in ticker else ticker
        ticker_full = f'{ticker_clean}.TW'

        stock = yf.Ticker(ticker_full)

        # Get financial statements
        try:
            financials = stock.financials  # 損益表 (Income Statement)
            balance_sheet = stock.balance_sheet  # 資產負債表 (Balance Sheet)
            cash_flow = stock.cashflow  # 現金流量表 (Cash Flow)
        except Exception as e:
            return {
                'error': f'Unable to fetch financial data: {str(e)}',
                'ticker': ticker_clean,
                'status': 'failed'
            }

        # Build response with most recent periods
        statements = []

        # Income Statement (損益表)
        if not financials.empty:
            most_recent_income = financials.iloc[:, 0]  # Most recent period
            statements.append({
                'type': '損益表 (Income Statement)',
                'period': str(financials.columns[0].date()),
                'data': {
                    'Total Revenue': most_recent_income.get('Total Revenue'),
                    'Operating Income': most_recent_income.get('Operating Income'),
                    'Net Income': most_recent_income.get('Net Income'),
                    'Gross Profit': most_recent_income.get('Gross Profit'),
                }
            })

        # Balance Sheet (資產負債表)
        if not balance_sheet.empty:
            most_recent_bs = balance_sheet.iloc[:, 0]  # Most recent period
            statements.append({
                'type': '資產負債表 (Balance Sheet)',
                'period': str(balance_sheet.columns[0].date()),
                'data': {
                    'Total Assets': most_recent_bs.get('Total Assets'),
                    'Total Liabilities': most_recent_bs.get('Total Liabilities'),
                    "Stockholders' Equity": most_recent_bs.get("Stockholders' Equity"),
                    'Current Assets': most_recent_bs.get('Current Assets'),
                    'Current Liabilities': most_recent_bs.get('Current Liabilities'),
                }
            })

        # Cash Flow (現金流量表)
        if not cash_flow.empty:
            most_recent_cf = cash_flow.iloc[:, 0]  # Most recent period
            statements.append({
                'type': '現金流量表 (Cash Flow Statement)',
                'period': str(cash_flow.columns[0].date()),
                'data': {
                    'Operating Cash Flow': most_recent_cf.get('Operating Cash Flow'),
                    'Free Cash Flow': most_recent_cf.get('Free Cash Flow'),
                    'Investing Cash Flow': most_recent_cf.get('Investing Cash Flow'),
                    'Financing Cash Flow': most_recent_cf.get('Financing Cash Flow'),
                }
            })

        return {
            'ticker': ticker_clean,
            'status': 'ok',
            'statements': statements,
            'note': 'Data from yfinance. Recent periods (最近期次)',
            'card_count': len(statements)
        }

    except Exception as e:
        return {
            'error': str(e),
            'ticker': ticker.replace('.TW', '') if '.TW' in ticker else ticker,
            'status': 'failed'
        }


def build_annual_report_summary(ticker: str) -> Dict[str, Any]:
    """Build Taiwan stock annual report summary (年報摘要).

    Args:
        ticker: Taiwan stock code (e.g., '2330')

    Returns:
        Dict with annual report highlights
    """
    try:
        ticker_clean = ticker.replace('.TW', '') if '.TW' in ticker else ticker
        ticker_full = f'{ticker_clean}.TW'

        stock = yf.Ticker(ticker_full)
        info = stock.info

        # Extract key annual metrics
        cards = []

        # Company Overview (公司概況)
        cards.append({
            'type': '公司概況 (Company Overview)',
            'title': f"{ticker_clean} {info.get('longName', ticker_clean)}",
            'subtitle': info.get('industry', 'N/A'),
            'details': {
                '產業': info.get('industry', 'N/A'),
                '員工數': info.get('fullTimeEmployees', 'N/A'),
                '網址': info.get('website', 'N/A'),
            }
        })

        # Financial Highlights (財務亮點)
        cards.append({
            'type': '財務亮點 (Financial Highlights)',
            'title': '過去12個月績效',
            'details': {
                '市值': f"${info.get('marketCap', 0) / 1e9:.1f}B",
                '營收': f"${info.get('totalRevenue', 0) / 1e9:.1f}B",
                '本益比': f"{info.get('trailingPE', 'N/A')}x",
                'ROE': f"{info.get('returnOnEquity', 0) * 100:.1f}%",
                '負債比': f"{info.get('debtToEquity', 0):.2f}x",
            }
        })

        # Dividend Information (股利資訊)
        if info.get('dividendRate'):
            cards.append({
                'type': '股利資訊 (Dividend)',
                'title': '股東回報',
                'details': {
                    '殖利率': f"{info.get('dividendYield', 0) * 100:.2f}%",
                    '配息': f"${info.get('dividendRate', 0):.2f}",
                    '配息率': f"{info.get('payoutRatio', 0) * 100:.1f}%",
                }
            })

        return {
            'ticker': ticker_clean,
            'status': 'ok',
            'cards': cards,
            'last_updated': info.get('lastDividendDate', 'N/A')
        }

    except Exception as e:
        return {
            'error': str(e),
            'ticker': ticker.replace('.TW', '') if '.TW' in ticker else ticker,
            'status': 'failed'
        }
