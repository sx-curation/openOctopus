"""Taiwan stock management metrics analysis."""
import yfinance as yf
from typing import Dict, Any, Optional
from datetime import datetime, timedelta


def build_management_metrics(ticker: str) -> Dict[str, Any]:
    """Build Taiwan stock management quality metrics.

    Guidance Accuracy - 目標達成度 (based on financial consistency)
    Strategy Execution - 策略執行力 (based on revenue/margin trends)
    Management Transparency - 管理透明度 (based on disclosure frequency)
    """
    try:
        ticker_clean = ticker.replace('.TW', '') if '.TW' in ticker else ticker
        ticker_full = f'{ticker_clean}.TW'

        stock = yf.Ticker(ticker_full)

        # Get financial data
        try:
            financials = stock.financials  # Income statement
            quarterly = stock.quarterly_financials if hasattr(stock, 'quarterly_financials') else None
            balance_sheet = stock.balance_sheet
            hist = stock.history(period='2y')
        except Exception as e:
            return {
                'error': f'Unable to fetch data: {str(e)}',
                'ticker': ticker_clean,
                'status': 'failed'
            }

        # Calculate metrics
        metrics = {
            'guidance_accuracy': _calculate_guidance_accuracy(financials, quarterly),
            'strategy_execution': _calculate_strategy_execution(financials, hist),
            'management_transparency': _calculate_transparency(stock),
        }

        return {
            'ticker': ticker_clean,
            'status': 'ok',
            'metrics': metrics,
            'last_updated': datetime.now().isoformat(),
            'data_source': 'yfinance + financial analysis'
        }

    except Exception as e:
        return {
            'error': str(e),
            'ticker': ticker.replace('.TW', '') if '.TW' in ticker else ticker,
            'status': 'failed'
        }


def _calculate_guidance_accuracy(financials, quarterly) -> Dict[str, Any]:
    """Calculate guidance accuracy score (目標達成度)
    Based on earnings consistency and stability."""
    try:
        if financials.empty:
            return {'score': 0, 'label': '資料不足', 'trend': 'neutral'}

        # Get last 4 quarters of net income
        recent = financials.iloc[:4] if len(financials) >= 4 else financials
        net_income = recent.get('Net Income')

        if net_income.isna().any():
            return {'score': 50, 'label': '部分資料', 'trend': 'neutral'}

        # Calculate consistency (lower variance = more accurate guidance)
        if len(net_income) >= 2:
            net_income_clean = net_income.dropna()
            if len(net_income_clean) >= 2:
                variance = net_income_clean.std() / (abs(net_income_clean.mean()) + 1e-9)
                # Convert variance to score (0-100)
                score = max(0, min(100, 100 - (variance * 50)))
            else:
                score = 70
        else:
            score = 70

        # Determine trend
        if len(net_income_clean) >= 2:
            trend = 'up' if net_income_clean.iloc[0] > net_income_clean.iloc[-1] else 'down'
        else:
            trend = 'neutral'

        return {
            'score': int(score),
            'label': f'{'高' if score >= 80 else '中' if score >= 50 else '低'}準確度',
            'trend': trend,
            'detail': f'淨利穩定性: {score:.0f}%'
        }
    except Exception:
        return {'score': 50, 'label': '無法計算', 'trend': 'neutral'}


def _calculate_strategy_execution(financials, history) -> Dict[str, Any]:
    """Calculate strategy execution score (策略執行力)
    Based on revenue growth and margin trends."""
    try:
        if financials.empty:
            return {'score': 0, 'label': '資料不足', 'trend': 'neutral'}

        # Get revenue and gross profit
        revenue = financials.get('Total Revenue')
        gross_profit = financials.get('Gross Profit')

        if revenue.isna().any() or gross_profit.isna().any():
            return {'score': 50, 'label': '部分資料', 'trend': 'neutral'}

        recent_revenue = revenue.iloc[:2] if len(revenue) >= 2 else revenue
        recent_gp = gross_profit.iloc[:2] if len(gross_profit) >= 2 else gross_profit

        # Revenue growth
        if len(recent_revenue) >= 2:
            revenue_growth = (recent_revenue.iloc[0] - recent_revenue.iloc[1]) / abs(recent_revenue.iloc[1])
            revenue_score = min(100, 50 + (revenue_growth * 100))
        else:
            revenue_score = 60

        # Gross margin trend
        recent_gp_clean = recent_gp.dropna()
        if len(recent_gp_clean) >= 2:
            gm1 = recent_gp_clean.iloc[0] / recent_revenue.iloc[0]
            gm2 = recent_gp_clean.iloc[1] / recent_revenue.iloc[1]
            margin_trend = 'up' if gm1 > gm2 else 'down'
            margin_score = 50 + ((gm1 - gm2) * 200)  # Scale margin change
        else:
            margin_trend = 'neutral'
            margin_score = 60

        # Combined score
        score = int((revenue_score + margin_score) / 2)
        score = max(0, min(100, score))

        return {
            'score': score,
            'label': f'{'優' if score >= 80 else '良' if score >= 60 else '可'}秀',
            'trend': margin_trend,
            'detail': f'營收成長+毛利率: {score:.0f}%'
        }
    except Exception:
        return {'score': 50, 'label': '無法計算', 'trend': 'neutral'}


def _calculate_transparency(stock) -> Dict[str, Any]:
    """Calculate management transparency score (管理透明度)
    Based on disclosure frequency and data availability."""
    try:
        info = stock.info

        # Check data completeness
        transparency_factors = {
            'has_financials': stock.financials is not None and not stock.financials.empty,
            'has_quarterly': hasattr(stock, 'quarterly_financials') and stock.quarterly_financials is not None,
            'has_info': bool(info),
            'has_website': bool(info.get('website')),
        }

        # Score based on factors
        score = sum(transparency_factors.values()) * 25

        # Additional boost for regular reporting
        if 'has_quarterly' in transparency_factors and transparency_factors['has_quarterly']:
            score = min(100, score + 10)

        label_map = {
            100: '非常高',
            75: '高',
            50: '中等',
            25: '低',
            0: '非常低'
        }

        label = next((v for k, v in sorted(label_map.items(), reverse=True) if score >= k), '未知')

        return {
            'score': int(score),
            'label': label,
            'trend': 'up',
            'detail': f'披露完整度: {int(score)}%',
            'factors': transparency_factors
        }
    except Exception:
        return {'score': 50, 'label': '無法計算', 'trend': 'neutral'}


def build_management_snapshot(ticker: str) -> Dict[str, Any]:
    """Build Taiwan management snapshot dashboard data."""
    result = build_management_metrics(ticker)

    if 'error' in result:
        return result

    # Format for dashboard display
    metrics = result.get('metrics', {})

    return {
        'ticker': result['ticker'],
        'status': 'ok',
        'cards': [
            {
                'type': '目標達成度',
                'title': 'Guidance Accuracy',
                'score': metrics.get('guidance_accuracy', {}).get('score', 0),
                'label': metrics.get('guidance_accuracy', {}).get('label', '無數據'),
                'detail': metrics.get('guidance_accuracy', {}).get('detail', ''),
            },
            {
                'type': '策略執行力',
                'title': 'Strategy Execution',
                'score': metrics.get('strategy_execution', {}).get('score', 0),
                'label': metrics.get('strategy_execution', {}).get('label', '無數據'),
                'detail': metrics.get('strategy_execution', {}).get('detail', ''),
            },
            {
                'type': '管理透明度',
                'title': 'Management Transparency',
                'score': metrics.get('management_transparency', {}).get('score', 0),
                'label': metrics.get('management_transparency', {}).get('label', '無數據'),
                'detail': metrics.get('management_transparency', {}).get('detail', ''),
            }
        ]
    }
