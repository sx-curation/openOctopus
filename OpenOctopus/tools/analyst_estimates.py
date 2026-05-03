import requests
import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from config import settings


def get_analyst_estimates(ticker: str) -> dict:
    """
    Returns recent quarters of EPS/revenue actuals vs. estimates (beat/miss),
    plus the next earnings date.

    Primary EPS source: yfinance earnings_dates.
    Revenue estimates: FMP API (falls back gracefully if key not set).
    """
    ticker = ticker.upper()
    result = {
        "ticker": ticker,
        "quarters": [],
        "next_earnings_date": None,
    }

    # --- EPS data from yfinance ---
    try:
        t = yf.Ticker(ticker)
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            # earnings_dates index is DatetimeIndex; positive surprises = beat
            past = ed[ed.index < pd.Timestamp.now(tz="UTC")].head(5)
            future = ed[ed.index >= pd.Timestamp.now(tz="UTC")]
            if not future.empty:
                result["next_earnings_date"] = str(future.index[-1].date())

            for dt, row in past.iterrows():
                eps_est = row.get("EPS Estimate")
                eps_act = row.get("Reported EPS")
                surprise = row.get("Surprise(%)")
                result["quarters"].append(
                    {
                        "date": str(dt.date()),
                        "eps_estimate": float(eps_est) if pd.notna(eps_est) else None,
                        "eps_actual": float(eps_act) if pd.notna(eps_act) else None,
                        "eps_surprise_pct": float(surprise) if pd.notna(surprise) else None,
                        "revenue_estimate": None,
                        "revenue_actual": None,
                        "revenue_surprise_pct": None,
                    }
                )
    except Exception as e:
        result["eps_error"] = str(e)

    # --- Revenue data from FMP (both endpoints fetched concurrently) ---
    if settings.FMP_API_KEY:
        estimates_url = (
            f"{settings.FMP_BASE_URL}/api/v3/analyst-estimates/{ticker}"
            f"?limit=5&apikey={settings.FMP_API_KEY}"
        )
        income_url = (
            f"{settings.FMP_BASE_URL}/api/v3/income-statement/{ticker}"
            f"?limit=5&apikey={settings.FMP_API_KEY}"
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            est_future = executor.submit(requests.get, estimates_url, timeout=10)
            inc_future = executor.submit(requests.get, income_url, timeout=10)
            try:
                est_resp = est_future.result()
            except Exception as e:
                result["revenue_error"] = str(e)
                est_resp = None
            try:
                inc_resp = inc_future.result()
            except Exception as e:
                result["revenue_actual_error"] = str(e)
                inc_resp = None

        # Process analyst estimates (revenue_estimate)
        try:
            if est_resp is not None and est_resp.ok:
                fmp_data = est_resp.json()
                fmp_by_date = {item.get("date", "")[:7]: item for item in fmp_data}
                for q in result["quarters"]:
                    fmp_item = fmp_by_date.get(q["date"][:7])
                    if fmp_item:
                        q["revenue_estimate"] = fmp_item.get("estimatedRevenueAvg")
        except Exception as e:
            result["revenue_error"] = str(e)

        # Process income actuals (revenue_actual + surprise vs estimate)
        try:
            if inc_resp is not None and inc_resp.ok:
                income_data = inc_resp.json()
                income_by_date = {item.get("date", "")[:7]: item for item in income_data}
                for q in result["quarters"]:
                    income_item = income_by_date.get(q["date"][:7])
                    if income_item:
                        rev = income_item.get("revenue")
                        q["revenue_actual"] = round(rev / 1e9, 2) if rev else None
                        if q["revenue_actual"] and q["revenue_estimate"]:
                            est_b = q["revenue_estimate"] / 1e9
                            q["revenue_estimate"] = round(est_b, 2)
                            q["revenue_surprise_pct"] = round(
                                (q["revenue_actual"] - est_b) / abs(est_b) * 100, 2
                            )
        except Exception as e:
            result["revenue_actual_error"] = str(e)
    else:
        result["revenue_note"] = "FMP_API_KEY not set; revenue estimates unavailable."

    return result
