from datetime import date

from datetime import datetime, timezone

import pandas as pd
import yfinance as yf


def get_quote(symbol: str) -> dict:
    ticker = symbol.upper()
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    try:
        fi = yf.Ticker(ticker).fast_info
        price = fi.last_price
        if price is None:
            return {"error": "ticker_not_found", "symbol": ticker, "source": "yahoo", "fetched_at": fetched_at}

        prev_close = fi.previous_close or price
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else None
        return {
            "symbol": ticker,
            "source": "yahoo",
            "fetched_at": fetched_at,
            "provider_symbol": ticker,
            "price": round(float(price), 2),
            "change_pct": round(float(change_pct), 2) if change_pct is not None else None,
            "open": None,
            "high": round(float(fi.day_high), 2) if fi.day_high is not None else None,
            "low": round(float(fi.day_low), 2) if fi.day_low is not None else None,
            "close": round(float(price), 2),
            "volume": int(fi.last_volume) if fi.last_volume is not None else None,
            "currency": fi.currency,
            "as_of": None,
        }
    except Exception as exc:
        return {"error": str(exc), "symbol": ticker, "source": "yahoo", "fetched_at": fetched_at}


def get_analyst_snapshot(symbol: str) -> dict:
    ticker = symbol.upper()
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    try:
        stock = yf.Ticker(ticker)
        targets = stock.get_analyst_price_targets() or {}
        recommendations = stock.get_recommendations_summary()

        recommendation_trend = []
        current_summary = None
        if recommendations is not None and not recommendations.empty:
            for _, row in recommendations.iterrows():
                item = {
                    "period": row.get("period"),
                    "strong_buy": int(row.get("strongBuy") or 0),
                    "buy": int(row.get("buy") or 0),
                    "hold": int(row.get("hold") or 0),
                    "sell": int(row.get("sell") or 0),
                    "strong_sell": int(row.get("strongSell") or 0),
                }
                item["score"] = _recommendation_score(item)
                recommendation_trend.append(item)

            current_summary = recommendation_trend[0]

        current_price = _as_float(targets.get("current"))
        mean_target = _as_float(targets.get("mean"))
        target_upside_pct = None
        if current_price and mean_target:
            target_upside_pct = round(((mean_target - current_price) / current_price) * 100, 2)

        if current_summary is None and current_price is None and mean_target is None:
            return {
                "error": "analyst_data_unavailable",
                "symbol": ticker,
                "source": "yahoo",
                "fetched_at": fetched_at,
            }

        return {
            "symbol": ticker,
            "source": "yahoo",
            "fetched_at": fetched_at,
            "provider_symbol": ticker,
            "price_targets": {
                "current": current_price,
                "mean": mean_target,
                "low": _as_float(targets.get("low")),
                "high": _as_float(targets.get("high")),
                "median": _as_float(targets.get("median")),
            },
            "target_upside_pct": target_upside_pct,
            "current_recommendation": current_summary,
            "recommendation_trend": recommendation_trend,
        }
    except Exception as exc:
        return {"error": str(exc), "symbol": ticker, "source": "yahoo", "fetched_at": fetched_at}


def get_daily_history(
    symbol: str,
    period: str = "6mo",
    start: date | str | None = None,
    end: date | str | None = None,
) -> dict:
    ticker = symbol.upper()

    try:
        history_kwargs = {"interval": "1d", "auto_adjust": False}
        if start or end:
            if start:
                history_kwargs["start"] = str(start)
            if end:
                history_kwargs["end"] = str(end)
        else:
            history_kwargs["period"] = period

        hist = yf.Ticker(ticker).history(**history_kwargs)
        if hist.empty:
            return {"error": "history_unavailable", "symbol": ticker, "source": "yahoo"}

        bars = []
        for idx, row in hist.iterrows():
            bars.append({
                "date": str(pd.Timestamp(idx).date()),
                "open": round(float(row["Open"]), 4) if pd.notna(row["Open"]) else None,
                "high": round(float(row["High"]), 4) if pd.notna(row["High"]) else None,
                "low": round(float(row["Low"]), 4) if pd.notna(row["Low"]) else None,
                "close": round(float(row["Close"]), 4) if pd.notna(row["Close"]) else None,
                "volume": int(row["Volume"]) if pd.notna(row["Volume"]) else None,
            })

        return {
            "symbol": ticker,
            "source": "yahoo",
            "provider_symbol": ticker,
            "interval": "1d",
            "period": period,
            "start": str(start) if start else None,
            "end": str(end) if end else None,
            "bars": bars,
        }
    except Exception as exc:
        return {"error": str(exc), "symbol": ticker, "source": "yahoo"}


def _as_float(value) -> float | None:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _recommendation_score(summary: dict) -> int | None:
    total = (
        summary["strong_buy"]
        + summary["buy"]
        + summary["hold"]
        + summary["sell"]
        + summary["strong_sell"]
    )
    if total <= 0:
        return None

    weighted = (
        summary["strong_buy"] * 100
        + summary["buy"] * 75
        + summary["hold"] * 50
        + summary["sell"] * 25
    )
    return round(weighted / total)
