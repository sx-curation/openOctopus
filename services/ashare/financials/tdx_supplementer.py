"""pytdx single-period financial data supplementer.

Fills in latest-period values missing from the AKShare multi-year fetch.
pytdx get_finance_info returns one record per stock (most recent quarter).
"""
from __future__ import annotations

import logging

from services.ashare import market_id, strip_suffix
from services.ashare.tdx_client import get_api, reset_api

logger = logging.getLogger(__name__)


def supplement(ticker: str, funda: dict, years: list) -> dict:
    """Use pytdx to fill funda[0] (latest period) for missing fields.

    Modifies funda in-place and returns it.
    Silently skips if pytdx is unavailable.
    """
    code = strip_suffix(ticker)
    mkt = market_id(ticker)
    try:
        api = get_api()
        data = api.get_finance_info(mkt, code)
    except Exception as e:
        logger.debug("tdx_supplementer: get_finance_info failed for %s: %s", ticker, e)
        try:
            reset_api()
        except Exception:
            pass
        return funda

    if not data:
        return funda

    d = data[0] if isinstance(data, list) else data

    def _fill(key: str, tdx_key: str, div: float = 1.0) -> None:
        """Fill funda[key][0] from pytdx if currently None."""
        series = funda.get(key, [])
        if series and series[0] is not None:
            return  # already populated from AKShare
        v = d.get(tdx_key)
        if v is None:
            return
        try:
            filled = float(v) / div
            if series:
                funda[key] = [filled] + list(series[1:])
            else:
                funda[key] = [filled]
        except (TypeError, ValueError):
            pass

    # pytdx finance_info field names (as returned by get_finance_info)
    # ROE: pytdx returns as decimal (e.g. 0.25 = 25%) — match AKShare's ÷100 convention
    _fill("returnOnEquity", "roe_weight")            # weighted ROE, decimal
    _fill("actualDebtRatio", "debt_to_assets")       # total liabilities / total assets, decimal

    logger.debug("tdx_supplementer: supplemented %s", ticker)
    return funda
