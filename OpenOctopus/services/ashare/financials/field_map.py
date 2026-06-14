"""AKShare stock_financial_analysis_indicator field mapping.

Verified against AKShare 1.18.64 with symbol='600519', start_year='2021'.
Column names confirmed via cols_out.txt (UTF-8 encoded).
"""
from __future__ import annotations

# Maps internal English key → actual AKShare column name (Chinese)
# Only includes fields confirmed present in the 86-column DataFrame.
RAW_FIELD_MAP: dict[str, str] = {
    "returnOnEquity":                "净资产收益率(%)",               # col 28
    "revenueGrowth":                 "主营业务收入增长率(%)",          # col 31
    "grossProfitMargin":             "销售毛利率(%)",                  # col 21
    "currentRatio":                  "流动比率",                       # col 45
    "DebtToEquity":                  "产权比率(%)",                    # col 58
    "receivablesTurnover_days":      "应收账款周转天数(天)",           # col 36
    "inventoryTurnover_days":        "存货周转天数(天)",               # col 37
    "interestCoverage":              "利息支付倍数",                   # col 48
    "operatingCashFlowToNetIncome":  "经营现金净流量与净利润的比率(%)", # col 65
    # Per-share raw values used for YoY calculation (not put into funda directly)
    "eps_raw":                       "摊薄每股收益(元)",               # col 1
    "fcf_per_share_raw":             "每股经营性现金流(元)",           # col 7
}

# Fields where AKShare returns percentage (e.g. 25.3 means 25.3%), need ÷100 for decimal
DIVISOR_100: frozenset[str] = frozenset({
    "returnOnEquity",
    "revenueGrowth",
    "grossProfitMargin",
    "DebtToEquity",
    "operatingCashFlowToNetIncome",
})


def validate_fields(df_columns: list[str]) -> dict[str, bool]:
    """Return {eng_key: available} for each key in RAW_FIELD_MAP.

    Call once per DataFrame to check field availability before extraction.
    Missing fields gracefully degrade to None-filled series.
    """
    return {eng: (cn in df_columns) for eng, cn in RAW_FIELD_MAP.items()}
