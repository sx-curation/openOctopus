"""A-share financial health fetcher — integrates AKShare + pytdx.

Output format is identical to fetch_financial_health() in services/financial_health/fetcher.py,
so scorer.py, app.py, and the LLM layer require zero modification.
"""
from __future__ import annotations

import logging

from services.ashare import market_id, strip_suffix
from services.ashare.tdx_client import get_api, reset_api

from .akshare_fetcher import fetch_multiyear
from .tdx_supplementer import supplement

logger = logging.getLogger(__name__)


def fetch_cn_financial_health(ticker: str) -> dict:
    """Fetch A-share financial health data.

    1. Primary: AKShare stock_financial_analysis_indicator (multi-year)
    2. Supplement: pytdx get_finance_info (latest period gap-fill)
    3. Returns same format as fetch_financial_health()
    """
    t = ticker.upper().strip()

    result = fetch_multiyear(t, start_year="2020")

    if result.get("error") or not result.get("years"):
        logger.warning("cn_fetcher: AKShare failed for %s (%s), trying pytdx fallback", t, result.get("error"))
        result = _tdx_fallback(t)

    result["fundamentals"] = supplement(t, result.get("fundamentals", {}), result.get("years", []))

    # Pad missing raw series keys expected by _build_result so it doesn't KeyError.
    # For A-shares many absolute-value fields are unavailable from indicator data.
    n = len(result.get("years", []))
    _ensure_raw_keys(result["fundamentals"], n)

    # Attempt to run _build_result for full derived-metric computation.
    # On incompatibility (trap #13 in plan), fall back to direct fundamentals dict.
    try:
        from services.financial_health.fetcher import _build_result
        akshare_funda = result["fundamentals"]
        built = _build_result(
            t,
            result["years"],
            akshare_funda,
            result.get("info", {}),
            precomputed=_extract_precomputed(akshare_funda),
        )
        # _build_result recomputes some fields from null raw series → patch with AKShare values
        _patch_akshare_fields(built["fundamentals"], akshare_funda)
        built["data_source"] = "akshare+pytdx"
        return built
    except Exception as e:
        logger.warning("cn_fetcher: _build_result failed for %s (%s), returning raw funda", t, e)
        result.setdefault("error", None)
        result["data_source"] = "akshare+pytdx"
        result["ticker"] = t
        return result


def _ensure_raw_keys(funda: dict, n: int) -> None:
    """Guarantee every key expected by _build_result exists (None-filled if missing)."""
    required = [
        "revenue", "gross_profit", "op_income", "ebit", "net_income", "eps_diluted",
        "interest_exp", "rd_exp", "sga_exp", "tax_rate_raw",
        "total_assets", "total_debt", "equity", "curr_assets", "curr_liab",
        "receivables", "inventory", "invested_cap", "deferred_rev",
        "op_cf", "capex", "fcf",
    ]
    pad = [None] * n
    for key in required:
        if key not in funda:
            funda[key] = list(pad)


def _patch_akshare_fields(built_funda: dict, akshare_funda: dict) -> None:
    """Re-inject AKShare-derived values for fields _build_result couldn't compute.

    _build_result derives revenueGrowth / grossProfitMargin / epsgrowth / freeCashFlowGrowth
    from raw absolute series (revenue, gross_profit, etc.) which are all-None for A-shares.
    We restore the AKShare-computed versions whenever they contain at least one non-None value.
    """
    patch_keys = [
        "revenueGrowth", "grossProfitMargin", "epsgrowth", "freeCashFlowGrowth",
        "receivablesTurnover_days", "inventoryTurnover_days", "interestCoverage",
        "operatingCashFlowToNetIncome", "EPS",
    ]
    for key in patch_keys:
        ak_vals = akshare_funda.get(key)
        if ak_vals and any(v is not None for v in ak_vals):
            built_funda[key] = ak_vals
    _fix_cn_edge_cases(built_funda)


def _fix_cn_edge_cases(funda: dict) -> None:
    """Fix known AKShare data issues specific to A-shares.

    利息支付倍数 goes negative when a company earns more interest than it pays
    (net interest income > 0, e.g. cash-rich companies like Kweichow Moutai).
    A negative value is NOT a risk signal — it means the company is a net lender.
    Setting to None causes scorer to skip the indicator rather than penalise it.
    """
    ic = funda.get("interestCoverage")
    if ic:
        funda["interestCoverage"] = [
            None if (v is not None and v < 0) else v for v in ic
        ]


def _extract_precomputed(funda: dict) -> dict:
    """Extract ratio fields that _build_result treats as precomputed overrides."""
    return {
        "roe":               funda.get("returnOnEquity"),
        "current_ratio":     funda.get("currentRatio"),
        "dte":               funda.get("DebtToEquity"),
        "gpm":               funda.get("grossProfitMargin"),
        "interest_coverage": funda.get("interestCoverage"),
    }


def _tdx_fallback(ticker: str) -> dict:
    """Last-resort: single-period data from pytdx get_finance_info."""
    code = strip_suffix(ticker)
    mkt = market_id(ticker)
    try:
        api = get_api()
        data = api.get_finance_info(mkt, code)
        if data:
            d = data[0] if isinstance(data, list) else data
            roe = d.get("roe_weight")
            return {
                "years": [2024],
                "fundamentals": {
                    "returnOnEquity": [float(roe)] if roe is not None else [None],
                },
                "info": {
                    "companyName": ticker,
                    "currency":    "CNY",
                    "sector":      "",
                    "industry":    "",
                    "beta":        None,
                    "trailingPE":  None,
                    "marketCap":   None,
                    "debtToEquity_raw": None,
                },
                "error": None,
            }
    except Exception as e:
        logger.warning("cn_fetcher: pytdx fallback failed for %s: %s", ticker, e)
        try:
            reset_api()
        except Exception:
            pass
    return {
        "years": [],
        "fundamentals": {},
        "info": {
            "companyName": ticker,
            "currency":    "CNY",
            "sector":      "",
            "industry":    "",
            "beta":        None,
            "trailingPE":  None,
            "marketCap":   None,
            "debtToEquity_raw": None,
        },
        "error": "all_sources_failed",
    }
