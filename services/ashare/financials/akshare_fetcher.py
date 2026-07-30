"""AKShare multi-year financial data fetcher for A-shares.

Primary data source: ak.stock_financial_analysis_indicator()
Returns 86-column quarterly DataFrame with per-share and ratio metrics.

Annual deduplication: AKShare returns quarterly data. We reduce to one row
per fiscal year, preferring the annual report (date ending "-12-31"). For the
current calendar year, we use the latest available quarter. This ensures
`years` contains unique annual labels (e.g. [2025, 2024, 2023, 2022, 2021]),
matching the format the scorer and frontend expect.
"""
from __future__ import annotations

import logging

import pandas as pd

from services.ashare import strip_suffix
from services.ashare.names import get_cn_name_map

from .field_map import DIVISOR_100, RAW_FIELD_MAP, validate_fields

logger = logging.getLogger(__name__)


def _annual_indices(date_vals: list[str]) -> list[int]:
    """Return indices of rows to keep for annual deduplication.

    Strategy (applied to oldest-first list, as AKShare returns):
    - Group rows by calendar year.
    - Within each year keep the row whose date ends "-12-31" (annual report).
    - If no -12-31 row exists for a year, keep the *latest* quarter for that year.

    Returns indices in the original oldest-first order.
    """
    from collections import defaultdict
    year_rows: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for idx, d in enumerate(date_vals):
        s = str(d)
        year = int(s[:4]) if len(s) >= 4 else 0
        year_rows[year].append((idx, s))

    keep: list[int] = []
    for year, rows in year_rows.items():
        # Prefer annual report (-12-31)
        annual = [i for i, d in rows if d.endswith("-12-31")]
        if annual:
            keep.append(annual[0])
        else:
            # Take latest quarter (largest date string = latest)
            latest_idx = max(rows, key=lambda t: t[1])[0]
            keep.append(latest_idx)

    return sorted(keep)  # restore original (oldest-first) order


def fetch_multiyear(ticker: str, start_year: str = "2020") -> dict:
    """Fetch multi-year annual financial data from AKShare.

    Returns:
        {
          "years": [2025, 2024, ...],       # newest first, one entry per year
          "fundamentals": {metric: [...]},  # aligned to years
          "info": {companyName, currency, ...},
          "error": None | str,
        }
    """
    import akshare as ak  # lazy import — keep module load fast

    code = strip_suffix(ticker)
    try:
        df = ak.stock_financial_analysis_indicator(symbol=code, start_year=start_year)
    except Exception as e:
        logger.warning("akshare_fetcher: fetch failed for %s: %s", ticker, e)
        return {"years": [], "fundamentals": {}, "info": {}, "error": str(e)}

    if df is None or df.empty:
        return {"years": [], "fundamentals": {}, "info": {}, "error": "empty_df"}

    # ── Annual deduplication ──────────────────────────────────────────────────
    date_col = df.columns[0]
    date_vals_all = [str(d) for d in df[date_col].tolist()]
    keep_idx = _annual_indices(date_vals_all)
    df = df.iloc[keep_idx].reset_index(drop=True)
    date_vals = [str(d) for d in df[date_col].tolist()]
    # ─────────────────────────────────────────────────────────────────────────

    avail = validate_fields(df.columns.tolist())
    n = len(df)

    # Build years list newest-first (AKShare returns oldest-first)
    years_raw = [int(d[:4]) for d in date_vals]
    years = list(reversed(years_raw))

    # Detect if the most-recent period is a partial year (not -12-31)
    newest_date = date_vals[-1]  # date_vals is oldest-first; -1 = newest
    _newest_is_partial = not newest_date.endswith("-12-31")

    def _series(cn_name: str, div: float = 1.0) -> list:
        """Extract a column as a list, converting NaN → None. Reversed (newest first)."""
        if cn_name not in df.columns:
            return [None] * n
        vals = [(float(v) / div) if pd.notna(v) and v == v else None for v in df[cn_name].tolist()]
        return list(reversed(vals))

    def _yoy(vals: list) -> list:
        """Compute YoY growth rates (newest first). Works on annual series only."""
        result = []
        for i in range(len(vals)):
            c = vals[i]
            p = vals[i + 1] if i + 1 < len(vals) else None
            if c is None or p is None or p == 0:
                result.append(None)
            else:
                result.append((c - p) / abs(p))
        return result

    funda: dict = {}

    # Map all non-raw fields
    for eng, cn in RAW_FIELD_MAP.items():
        if eng.endswith("_raw"):
            continue  # handled below via YoY
        if not avail.get(eng):
            logger.debug("akshare_fetcher: field %s (%s) not available for %s", eng, cn, ticker)
            continue
        div = 100.0 if eng in DIVISOR_100 else 1.0
        funda[eng] = _series(cn, div)

    # YoY growth from per-share raw values (annual series → valid YoY)
    eps_cn = RAW_FIELD_MAP.get("eps_raw", "")
    fcf_cn = RAW_FIELD_MAP.get("fcf_per_share_raw", "")
    eps_vals = _series(eps_cn, 1.0) if eps_cn in df.columns else [None] * n
    fcf_vals = _series(fcf_cn, 1.0) if fcf_cn in df.columns else [None] * n
    eps_yoy = _yoy(eps_vals)
    fcf_yoy = _yoy(fcf_vals)
    # Null out YoY for partial years (comparing Q1 to prior full year is meaningless)
    if _newest_is_partial and eps_yoy:
        eps_yoy[0] = None
    if _newest_is_partial and fcf_yoy:
        fcf_yoy[0] = None
    funda["epsgrowth"] = eps_yoy
    funda["freeCashFlowGrowth"] = fcf_yoy
    # Keep EPS as a series too (scorer uses it)
    if any(v is not None for v in eps_vals):
        funda["EPS"] = eps_vals

    # Resolve company name — name map uses full ticker format (e.g. "600519.SH")
    name_map = get_cn_name_map()
    company_name = name_map.get(ticker) or name_map.get(code) or ticker

    info = {
        "companyName": company_name,
        "sector":      "",
        "industry":    "",
        "currency":    "CNY",
        "beta":        None,
        "trailingPE":  None,
        "returnOnEquity": funda.get("returnOnEquity", [None])[0] if funda.get("returnOnEquity") else None,
        "marketCap":   None,
        "debtToEquity_raw": None,
    }

    return {"years": years, "fundamentals": funda, "info": info, "error": None}
