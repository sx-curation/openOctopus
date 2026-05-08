"""Financial Health Data Fetcher.

Fetches 4-5 years of annual fundamentals from yfinance and computes
all derived metrics needed by the scoring engine.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── helpers ──────────────────────────────────────────────────────────────────

def _safe_div(num, den):
    try:
        if num is None or den in (None, 0):
            return None
        n = float(num)
        d = float(den)
        if d == 0:
            return None
        return n / d
    except Exception:
        return None


def _pct_growth(curr, prev):
    """YoY percentage growth; returns None if inputs invalid."""
    try:
        c = float(curr)
        p = float(prev)
        if p == 0:
            return None
        return (c - p) / abs(p)
    except Exception:
        return None


def _to_float(val) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def _series_from_df(df, row_name: str) -> List[Optional[float]]:
    """Return list of values (newest first) for a row in a yfinance DataFrame."""
    try:
        if df is None or row_name not in df.index:
            return []
        row = df.loc[row_name]
        # yfinance columns are Timestamps, sorted newest-first
        vals = [_to_float(v) for v in row.values]
        return vals
    except Exception:
        return []


# ── main fetch function ───────────────────────────────────────────────────────

def fetch_financial_health(ticker: str) -> Dict[str, Any]:
    """Fetch 4-5 years of annual fundamentals and compute derived metrics.

    Returns:
        {
          ticker: str,
          years: [2024, 2023, ...],        # list of fiscal years (newest first)
          fundamentals: {metric: [v0, v1, v2, ...]},   # newest first
          info: {beta, trailingPE, returnOnEquity, marketCap, debtToEquity_raw},
          error: None | str
        }
    """
    import yfinance as yf
    import requests as _requests
    import pandas as pd

    t = ticker.upper().strip()
    try:
        session = _requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        stock = yf.Ticker(t, session=session)

        # ── pull raw statements ───────────────────────────────────────────
        income = stock.financials          # columns = dates (newest first)
        balance = stock.balance_sheet
        cashflow = stock.cashflow
        info = stock.info or {}

        # Determine years list from income statement columns
        if income is None or income.empty:
            return {"ticker": t, "years": [], "fundamentals": {}, "info": {}, "error": "No financial data found"}

        # Sort columns newest first
        try:
            income = income.sort_index(axis=1, ascending=False)
            balance = balance.sort_index(axis=1, ascending=False) if balance is not None and not balance.empty else pd.DataFrame()
            cashflow = cashflow.sort_index(axis=1, ascending=False) if cashflow is not None and not cashflow.empty else pd.DataFrame()
        except Exception:
            pass

        years = [int(str(c)[:4]) for c in income.columns]

        # ── extract raw series (newest first) ────────────────────────────
        revenue        = _series_from_df(income, "Total Revenue")
        gross_profit   = _series_from_df(income, "Gross Profit")
        op_income      = _series_from_df(income, "Operating Income")
        ebit           = _series_from_df(income, "EBIT") or op_income
        net_income     = _series_from_df(income, "Net Income")
        eps_diluted    = _series_from_df(income, "Diluted EPS")
        interest_exp   = _series_from_df(income, "Interest Expense")
        rd_exp         = _series_from_df(income, "Research And Development")
        sga_exp        = _series_from_df(income, "Selling General And Administration")
        tax_rate_raw   = _series_from_df(income, "Tax Rate For Calcs")

        total_assets   = _series_from_df(balance, "Total Assets")
        total_debt     = _series_from_df(balance, "Total Debt")
        equity         = _series_from_df(balance, "Common Stock Equity")
        curr_assets    = _series_from_df(balance, "Current Assets")
        curr_liab      = _series_from_df(balance, "Current Liabilities")
        receivables    = _series_from_df(balance, "Receivables")
        inventory      = _series_from_df(balance, "Inventory")
        invested_cap   = _series_from_df(balance, "Invested Capital")
        deferred_rev   = _series_from_df(balance, "Current Deferred Revenue")

        op_cf   = _series_from_df(cashflow, "Operating Cash Flow")
        capex   = _series_from_df(cashflow, "Capital Expenditure")   # negative values
        fcf     = _series_from_df(cashflow, "Free Cash Flow")

        n = len(years)

        # ── derived metrics ───────────────────────────────────────────────
        def _pad(lst): return (lst + [None] * n)[:n]

        revenue      = _pad(revenue)
        gross_profit = _pad(gross_profit)
        op_income    = _pad(op_income)
        ebit         = _pad(ebit)
        net_income   = _pad(net_income)
        eps_diluted  = _pad(eps_diluted)
        interest_exp = _pad(interest_exp)
        rd_exp       = _pad(rd_exp)
        sga_exp      = _pad(sga_exp)
        tax_rate_raw = _pad(tax_rate_raw)
        total_assets = _pad(total_assets)
        total_debt   = _pad(total_debt)
        equity       = _pad(equity)
        curr_assets  = _pad(curr_assets)
        curr_liab    = _pad(curr_liab)
        receivables  = _pad(receivables)
        inventory    = _pad(inventory)
        invested_cap = _pad(invested_cap)
        deferred_rev = _pad(deferred_rev)
        op_cf        = _pad(op_cf)
        capex        = _pad(capex)
        fcf          = _pad(fcf)

        # Effective capex (positive magnitude)
        capex_abs = [abs(v) if v is not None else None for v in capex]

        # FCF fallback: OCF - |capex|
        fcf_eff = [
            (op_cf[i] - capex_abs[i]) if (op_cf[i] is not None and capex_abs[i] is not None)
            else fcf[i]
            for i in range(n)
        ]

        # YoY growth series (newest first; index 0 = latest-to-prev)
        def _growth_series(lst):
            out = []
            for i in range(len(lst)):
                if i + 1 < len(lst):
                    out.append(_pct_growth(lst[i], lst[i + 1]))
                else:
                    out.append(None)
            return out

        rev_growth   = _growth_series(revenue)
        eps_growth   = _growth_series(eps_diluted)
        fcf_growth   = _growth_series(fcf_eff)
        capex_growth = _growth_series(capex_abs)
        deferred_growth = _growth_series(deferred_rev)

        # Ratios
        roe = [_safe_div(net_income[i], equity[i]) for i in range(n)]

        # ROIC = EBIT*(1-tax_rate) / (Debt + Equity)
        def _roic(i):
            try:
                ebit_v = ebit[i]
                tax_v  = tax_rate_raw[i] if tax_rate_raw[i] is not None else 0.21
                debt_v = total_debt[i] or 0.0
                eq_v   = equity[i]
                if ebit_v is None or eq_v is None:
                    return None
                nopat = float(ebit_v) * (1.0 - float(tax_v))
                invested = float(debt_v) + float(eq_v)
                return _safe_div(nopat, invested)
            except Exception:
                return None

        roic = [_roic(i) for i in range(n)]

        ocf_to_ni = [_safe_div(op_cf[i], net_income[i]) for i in range(n)]
        interest_coverage = [_safe_div(op_income[i], abs(interest_exp[i]) if interest_exp[i] else None) for i in range(n)]

        # D/E: yfinance info gives debtToEquity already as %, e.g. 79.5 means 0.795
        # But per-year we compute from balance sheet
        dte = [_safe_div(total_debt[i], equity[i]) for i in range(n)]

        current_ratio = [_safe_div(curr_assets[i], curr_liab[i]) for i in range(n)]
        gpm = [_safe_div(gross_profit[i], revenue[i]) for i in range(n)]
        actual_debt_ratio = [_safe_div(total_debt[i], total_assets[i]) for i in range(n)]

        # Receivables turnover days
        def _recv_days(i):
            r = receivables[i]
            rev = revenue[i]
            if r is None or rev is None or rev == 0:
                return None
            return float(r) / float(rev) * 365.0

        def _inv_days(i):
            inv = inventory[i]
            rev = revenue[i]
            if inv is None or rev is None or rev == 0:
                return None
            return float(inv) / float(rev) * 365.0

        recv_days = [_recv_days(i) for i in range(n)]
        inv_days  = [_inv_days(i) for i in range(n)]

        # Net interest income (interest expense sign: yfinance reports as negative)
        net_interest = [(-v if v is not None else None) for v in interest_exp]

        # ── assemble fundamentals dict ────────────────────────────────────
        funda = {
            # Raw financials
            "revenue":            revenue,
            "grossProfit":        gross_profit,
            "operatingIncome":    op_income,
            "netIncome":          net_income,
            "EPS":                eps_diluted,
            "interestExpense":    interest_exp,
            "RnD":                rd_exp,
            "SGA":                sga_exp,
            "operatingCashFlow":  op_cf,
            "capitalExpenditure": capex_abs,
            "freeCashFlow":       fcf_eff,
            "totalDebt":          total_debt,
            "totalEquity":        equity,
            "totalAssets":        total_assets,
            "currentAssets":      curr_assets,
            "currentLiabilities": curr_liab,
            "receivables":        receivables,
            "inventory":          inventory,
            "deferredRevenue":    deferred_rev,

            # Scoring metrics
            "returnOnEquity":                roe,
            "returnOnInvestedCapital":        roic,
            "operatingCashFlowToNetIncome":   ocf_to_ni,
            "epsgrowth":                      eps_growth,
            "revenueGrowth":                  rev_growth,
            "capitalExpenditure_growth_yoy":  capex_growth,
            "deferredRevenue_growth_yoy":     deferred_growth,
            "freeCashFlowGrowth":             fcf_growth,
            "interestCoverage":               interest_coverage,
            "DebtToEquity":                   dte,
            "actualDebtRatio":                actual_debt_ratio,
            "currentRatio":                   current_ratio,
            "grossProfitMargin":              gpm,
            "netInterestIncome":              net_interest,
            "receivablesTurnover_days":        recv_days,
            "inventoryTurnover_days":          inv_days,
        }

        # ── info dict ─────────────────────────────────────────────────────
        info_out = {
            "beta":            _to_float(info.get("beta")),
            "trailingPE":      _to_float(info.get("trailingPE")),
            "returnOnEquity":  _to_float(info.get("returnOnEquity")),
            "marketCap":       _to_float(info.get("marketCap")),
            "debtToEquity_raw": _to_float(info.get("debtToEquity")),  # in % form, e.g. 79.5
            "companyName":     info.get("longName") or info.get("shortName") or t,
            "sector":          info.get("sector") or "",
            "industry":        info.get("industry") or "",
            "currency":        info.get("currency") or "USD",
        }

        # Repeat scalar info values across years (for scoring engine compatibility)
        if info_out["beta"] is not None:
            funda["beta"] = [info_out["beta"]] * n
        if info_out["trailingPE"] is not None:
            funda["priceToEarningsRatio"] = [info_out["trailingPE"]] * n

        return {
            "ticker":       t,
            "years":        years,
            "fundamentals": funda,
            "info":         info_out,
            "error":        None,
        }

    except Exception as e:
        logger.exception("fetch_financial_health error for %s", ticker)
        return {"ticker": t, "years": [], "fundamentals": {}, "info": {}, "error": str(e)}
