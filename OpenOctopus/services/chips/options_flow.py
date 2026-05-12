"""
Chip Analysis - Options Flow
Computes PCR, Max Pain, and OI distribution from yfinance option chains.
Only fetches the first 3 expiry dates to cap latency.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import yfinance as yf


def fetch_options_flow(ticker: str) -> dict:
    t = ticker.upper()
    yticker = yf.Ticker(t)

    try:
        expiries = yticker.options  # tuple of expiry date strings
    except Exception as e:
        return {"ticker": t, "error": f"No options data: {e}", "fetched_at": _now()}

    if not expiries:
        return {"ticker": t, "error": "No options data available", "fetched_at": _now()}

    # Only fetch first 3 expiries to keep latency under 10s
    expiries_to_fetch = list(expiries[:3])

    # Fetch chains in parallel
    chains = {}

    def _fetch_chain(exp: str):
        return exp, yticker.option_chain(exp)

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(_fetch_chain, exp): exp for exp in expiries_to_fetch}
        for future in as_completed(futures, timeout=12):
            try:
                exp, chain = future.result()
                chains[exp] = chain
            except Exception:
                pass

    if not chains:
        return {"ticker": t, "error": "Failed to fetch option chains", "fetched_at": _now()}

    # Merge all calls and puts DataFrames
    import pandas as pd

    all_calls = pd.concat(
        [chains[e].calls for e in chains], ignore_index=True
    )
    all_puts = pd.concat(
        [chains[e].puts for e in chains], ignore_index=True
    )

    # Fill NaN in OI and volume columns
    for df in (all_calls, all_puts):
        for col in ("openInterest", "volume"):
            if col in df.columns:
                df[col] = df[col].fillna(0).astype(int)

    total_call_oi = int(all_calls["openInterest"].sum())
    total_put_oi = int(all_puts["openInterest"].sum())
    total_call_vol = int(all_calls.get("volume", pd.Series([0])).sum())
    total_put_vol = int(all_puts.get("volume", pd.Series([0])).sum())

    pcr_oi = round(total_put_oi / total_call_oi, 4) if total_call_oi > 0 else None
    pcr_volume = round(total_put_vol / total_call_vol, 4) if total_call_vol > 0 else None

    # Aggregate OI by strike
    calls_by_strike = (
        all_calls.groupby("strike")["openInterest"].sum().rename("call_oi")
    )
    puts_by_strike = (
        all_puts.groupby("strike")["openInterest"].sum().rename("put_oi")
    )
    oi_df = pd.concat([calls_by_strike, puts_by_strike], axis=1).fillna(0).astype(int)
    oi_df.index = oi_df.index.astype(float)
    oi_df = oi_df.reset_index().rename(columns={"strike": "strike"})
    oi_df["net_oi"] = oi_df["call_oi"] - oi_df["put_oi"]

    # Filter to current price ±30%
    try:
        current_price = float(yf.Ticker(t).info.get("regularMarketPrice") or
                              yf.Ticker(t).info.get("previousClose") or 0)
    except Exception:
        current_price = 0

    if current_price > 0:
        lo = current_price * 0.70
        hi = current_price * 1.30
        oi_df = oi_df[(oi_df["strike"] >= lo) & (oi_df["strike"] <= hi)]

    # Limit to 50 strikes max for chart readability
    if len(oi_df) > 50:
        step = max(1, len(oi_df) // 50)
        oi_df = oi_df.iloc[::step]

    # Max Pain: find strike that minimizes total ITM loss for option buyers
    all_strikes = sorted(oi_df["strike"].tolist())
    max_pain_strike = _calc_max_pain(all_calls, all_puts, all_strikes)

    oi_by_strike = oi_df.to_dict(orient="records")

    return {
        "ticker": t,
        "pcr_oi": pcr_oi,
        "pcr_volume": pcr_volume,
        "max_pain": max_pain_strike,
        "current_price": round(current_price, 2) if current_price else None,
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "expiries_used": list(chains.keys()),
        "oi_by_strike": oi_by_strike,
        "fetched_at": _now(),
        "error": None,
    }


def _calc_max_pain(calls_df, puts_df, strikes: list[float]) -> float | None:
    """Find strike price where total ITM option buyer losses are minimized."""
    if not strikes:
        return None

    import pandas as pd

    min_loss = None
    max_pain = None

    for k in strikes:
        # Call buyers lose when strike > k (their calls expire worthless)
        call_loss = float(
            ((calls_df["strike"] - k).clip(lower=0) * calls_df["openInterest"]).sum()
        )
        # Put buyers lose when strike < k (their puts expire worthless)
        put_loss = float(
            ((k - puts_df["strike"]).clip(lower=0) * puts_df["openInterest"]).sum()
        )
        total = call_loss + put_loss
        if min_loss is None or total < min_loss:
            min_loss = total
            max_pain = k

    return round(max_pain, 2) if max_pain is not None else None


def _now() -> str:
    return datetime.now().isoformat()[:19]
