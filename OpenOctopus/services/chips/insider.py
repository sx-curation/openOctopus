"""
Chip Analysis - Insider Trading (Form 4)
FMP /v4/insider-trading (primary) with yfinance insider_transactions fallback.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import requests

from config import settings


def fetch_insider(ticker: str) -> dict:
    t = ticker.upper()
    USE_FMP = bool(settings.FMP_API_KEY)

    if not USE_FMP:
        return _fetch_yfinance(t)

    try:
        url = f"{settings.FMP_BASE_URL}/api/v4/insider-trading"
        resp = requests.get(
            url,
            params={"symbol": t, "limit": 50, "apikey": settings.FMP_API_KEY},
            timeout=10,
        )

        if resp.status_code in (401, 403):
            return _fetch_yfinance(t, fmp_auth_failed=True)
        if resp.status_code == 404 or not resp.json():
            return _empty(t, "No insider data from FMP")

        data = resp.json()
        cutoff = datetime.now() - timedelta(days=180)
        transactions = []
        net_30d_buy = 0.0
        net_30d_sell = 0.0
        cutoff_30d = datetime.now() - timedelta(days=30)

        for tx in data[:50]:
            filing_str = tx.get("filingDate") or tx.get("transactionDate") or ""
            try:
                filing_dt = datetime.fromisoformat(filing_str[:10])
            except ValueError:
                filing_dt = None

            if filing_dt and filing_dt < cutoff:
                continue

            tx_type = tx.get("transactionType") or ""
            shares = abs(tx.get("securitiesTransacted") or 0)  # abs() for exercise/grant records
            price = float(tx.get("price") or 0)
            value = shares * price

            is_buy = "P-Purchase" in tx_type or "A-Award" in tx_type
            is_sell = "S-Sale" in tx_type

            transactions.append(
                {
                    "date": filing_str[:10],
                    "reporter": tx.get("reportingName") or tx.get("reportingCik") or "",
                    "position": tx.get("typeOfOwner") or "",
                    "transaction_type": "buy" if is_buy else ("sell" if is_sell else "other"),
                    "shares": int(shares),
                    "price": round(price, 2),
                    "value": round(value, 0),
                }
            )

            if filing_dt and filing_dt >= cutoff_30d:
                if is_buy:
                    net_30d_buy += value
                elif is_sell:
                    net_30d_sell += value

        net_30d_value = net_30d_buy - net_30d_sell
        if net_30d_buy == 0 and net_30d_sell == 0:
            insider_signal = "neutral"
        elif net_30d_value > 0:
            insider_signal = "buy"
        else:
            insider_signal = "sell"

        return {
            "ticker": t,
            "transactions": transactions[:20],
            "net_30d_value": round(net_30d_value, 0),
            "net_30d_buy": round(net_30d_buy, 0),
            "net_30d_sell": round(net_30d_sell, 0),
            "insider_signal": insider_signal,
            "data_source": "fmp",
            "fetched_at": _now(),
            "error": None,
        }

    except Exception as e:
        return _fetch_yfinance(t, fallback_reason=str(e))


def _fetch_yfinance(t: str, fmp_auth_failed: bool = False, fallback_reason: str = "") -> dict:
    import yfinance as yf

    try:
        yticker = yf.Ticker(t)
        df = yticker.insider_transactions
    except Exception as e:
        return _empty(t, f"yfinance error: {e}")

    if df is None or df.empty:
        return _empty(t, "No insider transaction data available")

    cutoff = datetime.now() - timedelta(days=180)
    cutoff_30d = datetime.now() - timedelta(days=30)
    transactions = []
    net_30d_buy = 0.0
    net_30d_sell = 0.0

    for _, row in df.iterrows():
        date_str = str(row.get("Start Date") or row.get("Date") or "")[:10]
        try:
            filing_dt = datetime.fromisoformat(date_str)
        except ValueError:
            filing_dt = None

        if filing_dt and filing_dt < cutoff:
            continue

        tx_raw = str(row.get("Transaction") or "").lower()
        is_buy = "buy" in tx_raw or "purchase" in tx_raw or "acquisition" in tx_raw
        is_sell = "sale" in tx_raw or "sell" in tx_raw

        shares = abs(int(row.get("Shares") or 0))
        value = abs(float(row.get("Value") or 0))

        transactions.append(
            {
                "date": date_str,
                "reporter": str(row.get("Insider") or ""),
                "position": str(row.get("Position") or ""),
                "transaction_type": "buy" if is_buy else ("sell" if is_sell else "other"),
                "shares": shares,
                "price": round(value / shares, 2) if shares > 0 else 0,
                "value": round(value, 0),
            }
        )

        if filing_dt and filing_dt >= cutoff_30d:
            if is_buy:
                net_30d_buy += value
            elif is_sell:
                net_30d_sell += value

    net_30d_value = net_30d_buy - net_30d_sell
    if net_30d_buy == 0 and net_30d_sell == 0:
        insider_signal = "neutral"
    elif net_30d_value > 0:
        insider_signal = "buy"
    else:
        insider_signal = "sell"

    reason = "FMP key not configured" if not fmp_auth_failed else "FMP subscription required"
    if fallback_reason:
        reason = fallback_reason

    return {
        "ticker": t,
        "transactions": transactions[:20],
        "net_30d_value": round(net_30d_value, 0),
        "net_30d_buy": round(net_30d_buy, 0),
        "net_30d_sell": round(net_30d_sell, 0),
        "insider_signal": insider_signal,
        "data_source": "yfinance",
        "fallback_reason": reason,
        "fetched_at": _now(),
        "error": None,
    }


def _empty(t: str, msg: str) -> dict:
    return {
        "ticker": t,
        "transactions": [],
        "net_30d_value": 0,
        "insider_signal": "neutral",
        "data_source": "none",
        "fetched_at": _now(),
        "error": msg,
    }


def _now() -> str:
    return datetime.now().isoformat()[:19]
