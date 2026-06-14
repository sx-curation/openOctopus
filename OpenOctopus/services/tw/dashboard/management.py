"""Taiwan stock management metrics analysis."""
import yfinance as yf
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import numpy as np


def _get_quarterly_history(ticker: str, quarters: int = 8) -> List[Dict[str, Any]]:
    """Extract 8 quarters of EPS beat/miss history from yfinance.

    Args:
        ticker: Taiwan stock code (e.g., '2330')
        quarters: Number of quarters to retrieve (default 8)

    Returns:
        List of quarterly data with beat/miss information
    """
    try:
        ticker_clean = ticker.replace('.TW', '') if '.TW' in ticker else ticker
        ticker_full = f'{ticker_clean}.TW'
        stock = yf.Ticker(ticker_full)

        # Get quarterly financial data
        quarterly = stock.quarterly_financials if hasattr(stock, 'quarterly_financials') else None
        if quarterly is None or quarterly.empty:
            return []

        history = []
        columns = quarterly.columns[:quarters]

        for i, col in enumerate(columns):
            try:
                net_income = quarterly.loc['Net Income', col] if 'Net Income' in quarterly.index else None
                if net_income is None or np.isnan(net_income):
                    continue

                # For Taiwan market: simplified beat/miss based on actual vs historical average
                # We use sequential comparison as true estimates are unavailable
                prev_income = quarterly.loc['Net Income', columns[i+1]] if i+1 < len(columns) else None

                if prev_income is not None and not np.isnan(prev_income) and prev_income != 0:
                    # Calculate surprise percentage relative to previous quarter
                    surprise_pct = ((net_income - prev_income) / abs(prev_income)) * 100
                else:
                    surprise_pct = 0

                # Classify as beat/miss
                if surprise_pct > 1:
                    status = 'beat'
                elif surprise_pct < -1:
                    status = 'miss'
                else:
                    status = 'in-line'

                if hasattr(col, 'strftime'):
                    year = col.year
                    month = col.month
                    quarter = (month - 1) // 3 + 1
                    quarter_date = f'{year}-Q{quarter}'
                else:
                    quarter_date = str(col)[:7]

                history.append({
                    'quarter': quarter_date,
                    'actual': float(net_income),
                    'estimate': float(prev_income) if prev_income and not np.isnan(prev_income) else None,
                    'surprise_pct': round(surprise_pct, 2),
                    'status': status
                })
            except:
                continue

        return history[:quarters]
    except Exception as e:
        return []


def _score_to_grade(score: float) -> str:
    """Convert score to grade letter.

    Args:
        score: Score from 0-100

    Returns:
        Grade letter: S, A, B, C, or D
    """
    if score >= 88:
        return 'S'  # Exceptional
    elif score >= 75:
        return 'A'  # Highly Reliable
    elif score >= 60:
        return 'B'  # Moderate
    elif score >= 45:
        return 'C'  # Inconsistent
    else:
        return 'D'  # Poor Accuracy


def _grade_label(grade: str) -> str:
    """Get Chinese label for grade."""
    labels = {
        'S': '非凡準確',
        'A': '高度可靠',
        'B': '中等水平',
        'C': '不夠一致',
        'D': '準確度差',
    }
    return labels.get(grade, '—')


def _variance_label(variance: float) -> str:
    """Get variance label based on standard deviation."""
    if variance <= 5:
        return f'±{variance:.1f}% · 波動性低'
    elif variance <= 20:
        return f'±{variance:.1f}% · 波動性中等'
    else:
        return f'±{variance:.1f}% · 波動性高'


def _calculate_guidance_accuracy_enhanced(ticker: str) -> Dict[str, Any]:
    """Calculate enhanced guidance accuracy with beat/miss history.

    Args:
        ticker: Taiwan stock code

    Returns:
        Enhanced guidance accuracy metrics with grade and history
    """
    try:
        # Get quarterly history
        history = _get_quarterly_history(ticker, quarters=8)

        if not history:
            return {
                'score': 0,
                'grade': '—',
                'label': '資料不足',
                'beat_count': 0,
                'miss_count': 0,
                'avg_surprise': 0,
                'variance_label': '—',
                'history': []
            }

        # Calculate statistics
        beat_count = sum(1 for h in history if h['surprise_pct'] > 1)
        miss_count = sum(1 for h in history if h['surprise_pct'] < -1)
        surprises = [h['surprise_pct'] for h in history]
        avg_surprise = sum(surprises) / len(surprises) if surprises else 0
        variance = float(np.std(surprises)) if len(surprises) > 1 else 0

        # Calculate score: beat ratio + consistency bonus
        beat_ratio = (beat_count / len(history)) * 100 if history else 0
        consistency_bonus = max(0, 20 - variance)  # Less variance = higher bonus
        score = beat_ratio * 0.7 + consistency_bonus * 0.3
        score = max(0, min(100, score))

        # Get grade and labels
        grade = _score_to_grade(score)
        label = _grade_label(grade)
        variance_label = _variance_label(variance)

        return {
            'score': int(score),
            'grade': grade,
            'label': label,
            'beat_count': beat_count,
            'miss_count': miss_count,
            'avg_surprise': round(avg_surprise, 2),
            'variance_label': variance_label,
            'history': history,
        }
    except Exception as e:
        return {
            'score': 0,
            'grade': '—',
            'label': '無法計算',
            'beat_count': 0,
            'miss_count': 0,
            'avg_surprise': 0,
            'variance_label': '—',
            'history': []
        }


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
            'guidance_accuracy': _calculate_guidance_accuracy_enhanced(ticker),
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
    """Build Taiwan management snapshot dashboard data with full heuristics."""
    result = build_management_metrics(ticker)

    if 'error' in result:
        return result

    # Format for dashboard display
    metrics = result.get('metrics', {})

    # Return enhanced response with full heuristics structure
    return {
        'ticker': result['ticker'],
        'status': 'ok',
        'heuristics': {
            'guidance_accuracy': metrics.get('guidance_accuracy', {}),
            'strategy_execution': metrics.get('strategy_execution', {}),
            'management_transparency': metrics.get('management_transparency', {}),
        },
        # Keep old 'cards' format for backward compatibility
        'cards': [
            {
                'type': '目標達成度',
                'title': 'Guidance Accuracy',
                'score': metrics.get('guidance_accuracy', {}).get('score', 0),
                'label': metrics.get('guidance_accuracy', {}).get('label', '無數據'),
                'detail': metrics.get('guidance_accuracy', {}).get('variance_label', ''),
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
