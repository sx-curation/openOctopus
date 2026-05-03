"""Taiwan stock financial data using yfinance.

Reference: Colab CH-03 第 300-316 行
"""
import yfinance as yf


def get_key_financials(ticker: str) -> dict:
    """Get financial metrics for Taiwan stock.

    Args:
        ticker: Stock code (e.g., '2330', '2330.TW')

    Returns:
        Dict with financial data or error
    """
    try:
        # Ensure .TW suffix
        if not ticker.endswith('.TW'):
            ticker = f"{ticker}.TW"

        t = yf.Ticker(ticker)
        info = t.info

        if not info or info.get("symbol") is None:
            return {"error": "ticker_not_found", "ticker": ticker}

        def _fmt_pct(v):
            return round(v * 100, 2) if v is not None else None

        def _fmt_b(v):
            """Format large numbers in billions."""
            if v is None:
                return None
            return round(v / 1e9, 2)

        return {
            "ticker": ticker,
            "company_name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            # Valuation
            "pe_ratio_trailing": info.get("trailingPE"),
            "pe_ratio_forward": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "price_to_sales": info.get("priceToSalesTrailing12Months"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
            # Earnings
            "eps_ttm": info.get("trailingEps"),
            "eps_forward": info.get("forwardEps"),
            # Revenue & growth
            "revenue_ttm_billions": _fmt_b(info.get("totalRevenue")),
            "revenue_growth_yoy_pct": _fmt_pct(info.get("revenueGrowth")),
            "earnings_growth_yoy_pct": _fmt_pct(info.get("earningsGrowth")),
            # Margins
            "gross_margin_pct": _fmt_pct(info.get("grossMargins")),
            "operating_margin_pct": _fmt_pct(info.get("operatingMargins")),
            "net_margin_pct": _fmt_pct(info.get("profitMargins")),
            # Balance sheet
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),
            # Returns & cash
            "return_on_equity_pct": _fmt_pct(info.get("returnOnEquity")),
            "return_on_assets_pct": _fmt_pct(info.get("returnOnAssets")),
            "free_cash_flow_billions": _fmt_b(info.get("freeCashflow")),
            # Shareholder returns
            "dividend_yield_pct": (
                round(info["dividendRate"] / info["currentPrice"] * 100, 2)
                if info.get("dividendRate") and info.get("currentPrice")
                else None
            ),
            "payout_ratio_pct": _fmt_pct(info.get("payoutRatio")),
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}
