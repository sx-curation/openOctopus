"""Financial Health Data Fetcher.

Fetches 4-5 years of annual fundamentals and computes
all derived metrics needed by the scoring engine.

Data source priority:
  US tickers (pure A-Z, 1-5 chars): FMP API first, yfinance fallback
  Non-US tickers: yfinance only
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from config import settings

logger = logging.getLogger(__name__)

_US_RE = re.compile(r'^(?:[A-Z]{1,5}|[A-Z]{1,4}\.[A-Z])$')
_DEFAULT_TAX_RATE = 0.21
_PRIMARY_KEYS = ("revenue", "net_income")


def _is_us_ticker(t: str) -> bool:
    return bool(_US_RE.match(t))


# ── helpers ───────────────────────────────────────────────────────────────────

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
        v = float(val)
        return None if (v != v or v == float('inf') or v == float('-inf')) else v
    except Exception:
        return None


def _series_from_df(df, row_name: str) -> List[Optional[float]]:
    """Return list of values (newest first) for a row in a yfinance DataFrame."""
    try:
        if df is None or row_name not in df.index:
            return []
        row = df.loc[row_name]
        return [_to_float(v) for v in row.values]
    except Exception:
        return []


_EPS_CANDIDATE_KEYS = ("Diluted EPS", "Basic EPS", "EPS", "Diluted Eps", "Basic Eps")


def _series_eps(df) -> List[Optional[float]]:
    """Return EPS series from income statement, trying multiple yfinance key names."""
    for key in _EPS_CANDIDATE_KEYS:
        vals = _series_from_df(df, key)
        if any(v is not None for v in vals):
            return vals
    return []


# ── computation core ──────────────────────────────────────────────────────────

def _build_result(
    t: str,
    years: list,
    raw: dict,
    info_scalars: dict,
    precomputed: dict | None = None,
) -> Dict[str, Any]:
    """Compute all derived metrics from raw series and assemble the return dict.

    raw keys (all list[float|None], newest-first, length == len(years)):
        revenue, gross_profit, op_income, ebit, net_income, eps_diluted,
        interest_exp, rd_exp, sga_exp, tax_rate_raw,
        total_assets, total_debt, equity, curr_assets, curr_liab,
        receivables, inventory, invested_cap, deferred_rev,
        op_cf, capex, fcf

    precomputed keys (optional; override locally-computed ratios when non-empty):
        roe, roic, interest_coverage, dte, current_ratio, gpm, pe
    """
    n = len(years)
    pc = precomputed or {}

    # Unpack raw so downstream computation lines stay unchanged
    revenue        = raw["revenue"]
    gross_profit   = raw["gross_profit"]
    op_income      = raw["op_income"]
    ebit           = raw["ebit"]
    net_income     = raw["net_income"]
    eps_diluted    = raw["eps_diluted"]
    interest_exp   = raw["interest_exp"]
    rd_exp         = raw["rd_exp"]
    sga_exp        = raw["sga_exp"]
    tax_rate_raw   = raw["tax_rate_raw"]
    total_assets   = raw["total_assets"]
    total_debt     = raw["total_debt"]
    equity         = raw["equity"]
    curr_assets    = raw["curr_assets"]
    curr_liab      = raw["curr_liab"]
    receivables    = raw["receivables"]
    inventory      = raw["inventory"]
    invested_cap   = raw["invested_cap"]  # noqa: F841 — reserved for future use
    deferred_rev   = raw["deferred_rev"]
    op_cf          = raw["op_cf"]
    capex          = raw["capex"]
    fcf            = raw["fcf"]

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
            out.append(_pct_growth(lst[i], lst[i + 1]) if i + 1 < len(lst) else None)
        return out

    rev_growth      = _growth_series(revenue)
    eps_growth      = _growth_series(eps_diluted)
    fcf_growth      = _growth_series(fcf_eff)
    capex_growth    = _growth_series(capex_abs)
    deferred_growth = _growth_series(deferred_rev)

    # Use precomputed ratio if it contains at least one non-None value, else compute locally
    def _use_pc(key, computed):
        vals = pc.get(key)
        if vals and any(v is not None for v in vals):
            return vals
        return computed

    roe = _use_pc("roe", [_safe_div(net_income[i], equity[i]) for i in range(n)])

    def _roic_i(i):
        try:
            ebit_v = ebit[i]
            tax_v  = tax_rate_raw[i] if tax_rate_raw[i] is not None else _DEFAULT_TAX_RATE
            debt_v = total_debt[i] or 0.0
            eq_v   = equity[i]
            if ebit_v is None or eq_v is None:
                return None
            nopat    = float(ebit_v) * (1.0 - float(tax_v))
            invested = float(debt_v) + float(eq_v)
            return _safe_div(nopat, invested)
        except Exception:
            return None

    roic = _use_pc("roic", [_roic_i(i) for i in range(n)])

    ocf_to_ni = [_safe_div(op_cf[i], net_income[i]) for i in range(n)]

    interest_coverage = _use_pc(
        "interest_coverage",
        [_safe_div(op_income[i], abs(interest_exp[i]) if interest_exp[i] else None) for i in range(n)],
    )

    dte           = _use_pc("dte",           [_safe_div(total_debt[i], equity[i]) for i in range(n)])
    current_ratio = _use_pc("current_ratio", [_safe_div(curr_assets[i], curr_liab[i]) for i in range(n)])
    gpm           = _use_pc("gpm",           [_safe_div(gross_profit[i], revenue[i]) for i in range(n)])

    actual_debt_ratio = [_safe_div(total_debt[i], total_assets[i]) for i in range(n)]

    def _recv_days(i):
        r, rev = receivables[i], revenue[i]
        if r is None or rev is None or rev == 0:
            return None
        return float(r) / float(rev) * 365.0

    def _inv_days(i):
        inv, rev = inventory[i], revenue[i]
        if inv is None or rev is None or rev == 0:
            return None
        return float(inv) / float(rev) * 365.0

    recv_days = [_recv_days(i) for i in range(n)]
    inv_days  = [_inv_days(i) for i in range(n)]

    # Negate interest_exp: positive expense → negative net_interest → risk penalty fires
    net_interest = [(-v if v is not None else None) for v in interest_exp]

    funda = {
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

    info_out = {
        "beta":             info_scalars.get("beta"),
        "trailingPE":       info_scalars.get("trailingPE"),
        "returnOnEquity":   info_scalars.get("returnOnEquity"),
        "marketCap":        info_scalars.get("marketCap"),
        "debtToEquity_raw": info_scalars.get("debtToEquity_raw"),
        "companyName":      info_scalars.get("companyName") or t,
        "sector":           info_scalars.get("sector") or "",
        "industry":         info_scalars.get("industry") or "",
        "currency":         info_scalars.get("currency") or "USD",
    }

    # P/E: precomputed series takes precedence, then scalar from info
    pe_series = pc.get("pe")
    if pe_series and any(v is not None for v in pe_series):
        funda["priceToEarningsRatio"] = pe_series
    elif info_out["trailingPE"] is not None:
        funda["priceToEarningsRatio"] = [info_out["trailingPE"]] * n

    if info_out["beta"] is not None:
        funda["beta"] = [info_out["beta"]] * n

    return {
        "ticker":       t,
        "years":        years,
        "fundamentals": funda,
        "info":         info_out,
        "error":        None,
    }


# ── data sources ──────────────────────────────────────────────────────────────

def _extract_yfinance(t: str):
    """Extract raw financial series from yfinance.

    Returns (years, raw_dict, info_scalars).
    Raises on empty income statement.
    """
    import yfinance as yf
    import pandas as pd
    from services.ashare import to_yf_ticker

    yf_sym  = to_yf_ticker(t)   # .SH → .SS for Shanghai stocks
    stock   = yf.Ticker(yf_sym)
    income  = stock.financials
    balance = stock.balance_sheet
    cashflow = stock.cashflow
    info    = stock.info or {}

    if income is None or income.empty:
        raise ValueError("No financial data found in yfinance")

    try:
        income   = income.sort_index(axis=1, ascending=False)
        balance  = balance.sort_index(axis=1, ascending=False) if balance is not None and not balance.empty else pd.DataFrame()
        cashflow = cashflow.sort_index(axis=1, ascending=False) if cashflow is not None and not cashflow.empty else pd.DataFrame()
    except Exception:
        pass

    years = [int(str(c)[:4]) for c in income.columns]
    n     = len(years)

    def _pad(lst):
        return (lst + [None] * n)[:n]

    ebit_raw = _series_from_df(income, "EBIT")
    raw = {
        "revenue":       _pad(_series_from_df(income, "Total Revenue")),
        "gross_profit":  _pad(_series_from_df(income, "Gross Profit")),
        "op_income":     _pad(_series_from_df(income, "Operating Income")),
        "ebit":          _pad(ebit_raw if ebit_raw else _series_from_df(income, "Operating Income")),
        "net_income":    _pad(_series_from_df(income, "Net Income")),
        "eps_diluted":   _pad(_series_eps(income)),
        "interest_exp":  _pad(_series_from_df(income, "Interest Expense")),
        "rd_exp":        _pad(_series_from_df(income, "Research And Development")),
        "sga_exp":       _pad(_series_from_df(income, "Selling General And Administration")),
        "tax_rate_raw":  _pad(_series_from_df(income, "Tax Rate For Calcs")),
        "total_assets":  _pad(_series_from_df(balance, "Total Assets")),
        "total_debt":    _pad(_series_from_df(balance, "Total Debt")),
        "equity":        _pad(_series_from_df(balance, "Common Stock Equity")),
        "curr_assets":   _pad(_series_from_df(balance, "Current Assets")),
        "curr_liab":     _pad(_series_from_df(balance, "Current Liabilities")),
        "receivables":   _pad(_series_from_df(balance, "Receivables")),
        "inventory":     _pad(_series_from_df(balance, "Inventory")),
        "invested_cap":  _pad(_series_from_df(balance, "Invested Capital")),
        "deferred_rev":  _pad(_series_from_df(balance, "Current Deferred Revenue")),
        "op_cf":         _pad(_series_from_df(cashflow, "Operating Cash Flow")),
        "capex":         _pad(_series_from_df(cashflow, "Capital Expenditure")),
        "fcf":           _pad(_series_from_df(cashflow, "Free Cash Flow")),
    }

    # P/E fallback chain for non-US tickers (A-shares often missing trailingPE)
    trailing_pe = _to_float(info.get("trailingPE"))
    if not trailing_pe or trailing_pe <= 0:
        # Try computing from current price / trailing EPS
        price = _to_float(
            info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose")
        )
        t_eps = _to_float(info.get("trailingEps"))
        if price and t_eps and t_eps > 0:
            trailing_pe = round(price / t_eps, 2)
        else:
            # Last resort: forward P/E
            fpe = _to_float(info.get("forwardPE"))
            if fpe and fpe > 0:
                trailing_pe = fpe

    info_scalars = {
        "beta":             _to_float(info.get("beta")),
        "trailingPE":       trailing_pe,
        "returnOnEquity":   _to_float(info.get("returnOnEquity")),
        "marketCap":        _to_float(info.get("marketCap")),
        "debtToEquity_raw": _to_float(info.get("debtToEquity")),
        "companyName":      info.get("longName") or info.get("shortName") or t,
        "sector":           info.get("sector") or "",
        "industry":         info.get("industry") or "",
        "currency":         info.get("currency") or "USD",
    }

    return years, raw, info_scalars


def _extract_fmp(t: str):
    """Extract raw financial series from FMP API (5 calls).

    Returns (years, raw_dict, info_scalars, precomputed).
    Raises ValueError if statements are empty or API fails.
    """
    from .competitor import _fmp_stable_get  # lazy import to avoid circular at module load

    _p = {"symbol": t, "limit": 9, "period": "annual"}
    inc  = _fmp_stable_get("/income-statement",        _p)
    bal  = _fmp_stable_get("/balance-sheet-statement", _p)
    cf   = _fmp_stable_get("/cash-flow-statement",     _p)
    km   = _fmp_stable_get("/key-metrics",             _p)
    prof = _fmp_stable_get("/profile",                 {"symbol": t})
    # stable /profile may return a list or a single object — normalise to list
    if isinstance(prof, dict):
        prof = [prof]

    if not inc or not bal or not cf:
        raise ValueError("FMP returned empty statements")

    n     = min(len(inc), len(bal), len(cf))
    if n == 0:
        raise ValueError("No overlapping years from FMP")

    def _year(item: dict) -> int:
        cy = item.get("calendarYear")
        return int(cy) if cy else int(str(item["date"])[:4])

    years = [_year(inc[i]) for i in range(n)]

    def _g(lst: list, key: str, i: int) -> Optional[float]:
        try:
            return _to_float(lst[i].get(key))
        except (IndexError, AttributeError):
            return None

    def _tax_rate(i: int) -> Optional[float]:
        tax = _to_float(inc[i].get("incomeTaxExpense"))
        ebt = _to_float(inc[i].get("incomeBeforeTax"))
        if tax is None or ebt is None or ebt == 0:
            return None
        rate = tax / ebt
        # clamp to [0, 0.5] — negative or >50% rates are data artifacts
        return rate if 0 <= rate <= 0.5 else None

    raw = {
        "revenue":       [_g(inc, "revenue", i)                                    for i in range(n)],
        "gross_profit":  [_g(inc, "grossProfit", i)                                for i in range(n)],
        "op_income":     [_g(inc, "operatingIncome", i)                            for i in range(n)],
        "ebit":          [_g(inc, "operatingIncome", i)                            for i in range(n)],  # FMP has no explicit ebit field
        "net_income":    [_g(inc, "netIncome", i)                                  for i in range(n)],
        "eps_diluted":   [_g(inc, "epsdiluted", i)                                 for i in range(n)],
        "interest_exp":  [_g(inc, "interestExpense", i)                            for i in range(n)],  # positive in FMP
        "rd_exp":        [_g(inc, "researchAndDevelopmentExpenses", i)             for i in range(n)],
        "sga_exp":       [_g(inc, "sellingGeneralAndAdministrativeExpenses", i)    for i in range(n)],
        "tax_rate_raw":  [_tax_rate(i)                                             for i in range(n)],
        "total_assets":  [_g(bal, "totalAssets", i)                                for i in range(n)],
        "total_debt":    [_g(bal, "totalDebt", i)                                  for i in range(n)],
        "equity":        [_g(bal, "totalStockholdersEquity", i) or _g(bal, "totalEquity", i) for i in range(n)],
        "curr_assets":   [_g(bal, "totalCurrentAssets", i)                         for i in range(n)],
        "curr_liab":     [_g(bal, "totalCurrentLiabilities", i)                    for i in range(n)],
        "receivables":   [_g(bal, "netReceivables", i)                             for i in range(n)],
        "inventory":     [_g(bal, "inventory", i)                                  for i in range(n)],
        "deferred_rev":  [_g(bal, "deferredRevenue", i)                            for i in range(n)],
        "invested_cap":  [
            _safe_div((_g(bal, "totalDebt", i) or 0) + (_g(bal, "totalStockholdersEquity", i) or 0), 1)
            for i in range(n)
        ],
        "op_cf":         [_g(cf, "operatingCashFlow", i)                           for i in range(n)],
        "capex":         [_g(cf, "capitalExpenditure", i)                          for i in range(n)],  # negative in FMP
        "fcf":           [_g(cf, "freeCashFlow", i)                                for i in range(n)],
    }

    # Align key-metrics by calendarYear
    km_by_year: dict[int, dict] = {}
    for item in (km or []):
        try:
            yr = int(item.get("calendarYear") or str(item["date"])[:4])
            km_by_year[yr] = item
        except Exception:
            pass

    def _km(key: str, yr: int) -> Optional[float]:
        item = km_by_year.get(yr)
        return _to_float(item.get(key)) if item else None

    precomputed = {
        "roe":               [_km("returnOnEquity",         years[i]) for i in range(n)],
        "roic":              [_km("returnOnInvestedCapital", years[i]) for i in range(n)],
        "interest_coverage": [_km("interestCoverage",       years[i]) for i in range(n)],
        "dte":               [_km("debtToEquity",           years[i]) for i in range(n)],
        "current_ratio":     [_km("currentRatio",           years[i]) for i in range(n)],
        "gpm":               [_km("grossProfitMargin",      years[i]) for i in range(n)],
        "pe":                [_km("peRatio",                years[i]) for i in range(n)],
    }

    p = prof[0] if prof else {}
    info_scalars = {
        "beta":             _to_float(p.get("beta")),
        "trailingPE":       _to_float(p.get("pe")),
        "returnOnEquity":   _to_float(p.get("returnOnEquity")),
        "marketCap":        _to_float(p.get("mktCap")),
        "debtToEquity_raw": _to_float(p.get("debtToEquity")),
        "companyName":      p.get("companyName") or t,
        "sector":           p.get("sector") or "",
        "industry":         p.get("industry") or "",
        "currency":         p.get("currency") or "USD",
    }

    return years, raw, info_scalars, precomputed


# ── public API ────────────────────────────────────────────────────────────────

def _fetch_primary(t: str):
    """FMP-first for US tickers with FMP key; yfinance fallback."""
    if _is_us_ticker(t) and bool(settings.FMP_API_KEY):
        try:
            years, raw, info_scalars, precomputed = _extract_fmp(t)
            try:
                import yfinance as yf
                yf_info = yf.Ticker(t).info or {}
                for k, yk in [("beta", "beta"), ("trailingPE", "trailingPE"),
                               ("returnOnEquity", "returnOnEquity"), ("marketCap", "marketCap")]:
                    if info_scalars.get(k) is None:
                        v = _to_float(yf_info.get(yk))
                        if v is not None:
                            info_scalars[k] = v
            except Exception:
                pass
            return years, raw, info_scalars, precomputed, "fmp"
        except Exception as e:
            logger.warning("FMP primary failed %s: %s, falling back yfinance", t, e)
    years, raw, info_scalars = _extract_yfinance(t)
    while years and all(not raw.get(k) or raw[k][-1] is None for k in _PRIMARY_KEYS):
        years = years[:-1]
        raw = {k: v[:-1] for k, v in raw.items()}
    return years, raw, info_scalars, None, "yfinance"


def fetch_financial_health(ticker: str) -> Dict[str, Any]:
    """Fetch up to 9 years of annual fundamentals (FMP-first for US tickers) and compute derived metrics.

    Returns:
        {
          ticker: str,
          years: [2024, 2023, ...],
          fundamentals: {metric: [v0, v1, v2, ...]},
          info: {beta, trailingPE, returnOnEquity, marketCap, debtToEquity_raw, ...},
          data_source: "fmp" | "yfinance",
          error: None | str
        }
    """
    t = ticker.upper().strip()
    try:
        years, raw, info_scalars, precomputed, source = _fetch_primary(t)
        result = _build_result(t, years, raw, info_scalars, precomputed)
        result["data_source"] = source
        return result
    except Exception as e:
        logger.exception("fetch_financial_health error for %s", ticker)
        return {"ticker": t, "years": [], "fundamentals": {}, "info": {}, "data_source": "error", "error": str(e)}
