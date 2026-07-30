from datetime import timedelta

import pandas as pd

from data_sources.market.service import get_market_analyst_snapshot, get_market_history
from tools.analyst_estimates import get_analyst_estimates

# Beat/miss thresholds (EPS surprise %)
_BIG_BEAT_THRESHOLD = 10.0
_BEAT_THRESHOLD = 1.0
_MISS_THRESHOLD = -1.0
_BIG_MISS_THRESHOLD = -10.0


def _beat_miss_label(eps_surprise_pct: float | None) -> tuple[str, str]:
    """Return (label, color_key) for a given EPS surprise percentage."""
    if eps_surprise_pct is None:
        return "N/A", "neutral"
    if eps_surprise_pct >= _BIG_BEAT_THRESHOLD:
        return f"BIG BEAT +{eps_surprise_pct:.1f}%", "big_beat"
    if eps_surprise_pct >= _BEAT_THRESHOLD:
        return f"BEAT +{eps_surprise_pct:.1f}%", "beat"
    if eps_surprise_pct > _MISS_THRESHOLD:
        return f"IN LINE {eps_surprise_pct:+.1f}%", "inline"
    if eps_surprise_pct > _BIG_MISS_THRESHOLD:
        return f"MISS {eps_surprise_pct:.1f}%", "miss"
    return f"BIG MISS {eps_surprise_pct:.1f}%", "big_miss"


def build_earnings_cycle(ticker: str, limit: int = 3, window_days: int = 5) -> dict:
    ticker = ticker.upper()
    estimates = get_analyst_estimates(ticker)
    quarters = estimates.get("quarters", [])[:limit]

    if not quarters:
        return {
            "error": "earnings_quarters_unavailable",
            "ticker": ticker,
            "detail": estimates.get("eps_error") or "No historical earnings quarters available.",
        }

    items = []
    for quarter in quarters:
        event_date = pd.Timestamp(quarter["date"]).date()
        history = get_market_history(
            ticker,
            start=event_date - timedelta(days=10),
            end=event_date + timedelta(days=10),
        )

        eps_surprise = quarter.get("eps_surprise_pct")
        label, color_key = _beat_miss_label(eps_surprise)

        item = {
            "quarter_label": _quarter_label(event_date),
            "event_date": str(event_date),
            "eps_estimate": quarter.get("eps_estimate"),
            "eps_actual": quarter.get("eps_actual"),
            "eps_surprise_pct": eps_surprise,
            "beat_miss_label": label,
            "beat_miss_color": color_key,
            "revenue_estimate": quarter.get("revenue_estimate"),
            "revenue_actual": quarter.get("revenue_actual"),
            "revenue_surprise_pct": quarter.get("revenue_surprise_pct"),
        }

        if "error" in history:
            item.update({
                "status": "unavailable",
                "history_error": history["error"],
                "providers": history.get("providers"),
            })
            items.append(item)
            continue

        item.update(_build_price_window(history, event_date, window_days))
        items.append(item)

    # Analyst target price (current snapshot)
    analyst_target: dict | None = None
    try:
        snapshot = get_market_analyst_snapshot(ticker)
        if "error" not in snapshot:
            pt = snapshot.get("price_targets", {})
            analyst_target = {
                "mean": pt.get("mean"),
                "low": pt.get("low"),
                "high": pt.get("high"),
                "current_price": pt.get("current"),
                "upside_pct": snapshot.get("target_upside_pct"),
            }
    except Exception:
        pass

    return {
        "ticker": ticker,
        "window_days": window_days,
        "quarters": items,
        "next_earnings_date": estimates.get("next_earnings_date"),
        "revenue_note": estimates.get("revenue_note"),
        "analyst_target": analyst_target,
        "summary": _build_summary(items),
    }


def _build_price_window(history: dict, event_date, window_days: int) -> dict:
    bars = history.get("bars", [])
    if len(bars) < (window_days * 2 + 1):
        return {
            "status": "unavailable",
            "history_error": "insufficient_price_window",
            "history_source": history.get("source"),
            "history_bar_count": len(bars),
        }

    frame = pd.DataFrame(bars)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").reset_index(drop=True)
    frame["prev_close"] = frame["close"].shift(1)
    frame["daily_return_pct"] = ((frame["close"] - frame["prev_close"]) / frame["prev_close"] * 100).round(2)

    anchor_idx = _select_anchor_index(frame, pd.Timestamp(event_date))
    if anchor_idx is None:
        return {
            "status": "unavailable",
            "history_error": "anchor_date_not_found",
            "history_source": history.get("source"),
        }

    pre = frame.iloc[max(0, anchor_idx - window_days):anchor_idx]
    post = frame.iloc[anchor_idx + 1:anchor_idx + 1 + window_days]
    if len(pre) < window_days or len(post) < window_days:
        return {
            "status": "unavailable",
            "history_error": "insufficient_anchor_window",
            "history_source": history.get("source"),
            "anchor_date": str(frame.iloc[anchor_idx]["date"].date()),
        }

    day0 = frame.iloc[anchor_idx]
    start_close = pre.iloc[0]["close"]
    end_close = post.iloc[-1]["close"]
    window_return = round(((end_close - start_close) / start_close) * 100, 2) if start_close else None

    return {
        "status": "ok",
        "history_source": history.get("source"),
        "anchor_date": str(day0["date"].date()),
        "pre_days": _serialize_window(pre, "pre"),
        "day0": _serialize_point(day0, "day0", 0),
        "post_days": _serialize_window(post, "post"),
        "window_return_pct": window_return,
    }


def _select_anchor_index(frame: pd.DataFrame, event_ts: pd.Timestamp) -> int | None:
    on_or_after = frame.index[frame["date"] >= event_ts]
    if len(on_or_after) > 0:
        return int(on_or_after[0])

    before = frame.index[frame["date"] < event_ts]
    if len(before) > 0:
        return int(before[-1])
    return None


def _serialize_window(frame: pd.DataFrame, phase: str) -> list[dict]:
    items = []
    for offset, (_, row) in enumerate(frame.iterrows(), start=1):
        signed_offset = -offset if phase == "pre" else offset
        items.append(_serialize_point(row, phase, signed_offset))
    if phase == "pre":
        return list(reversed(items))
    return items


def _serialize_point(row, phase: str, offset: int) -> dict:
    return {
        "phase": phase,
        "offset": offset,
        "date": str(pd.Timestamp(row["date"]).date()),
        "close": round(float(row["close"]), 4) if pd.notna(row["close"]) else None,
        "daily_return_pct": round(float(row["daily_return_pct"]), 2) if pd.notna(row["daily_return_pct"]) else None,
    }


def _quarter_label(event_date) -> str:
    ts = pd.Timestamp(event_date)
    return f"{ts.year}-Q{ts.quarter}"


def _build_summary(items: list[dict]) -> dict:
    """Aggregate beat/miss statistics and post-earnings price patterns."""
    beats, misses, inline_count = [], [], []
    beat_returns, miss_returns = [], []

    for item in items:
        color = item.get("beat_miss_color")
        ret = item.get("window_return_pct")
        if color in ("big_beat", "beat"):
            beats.append(item)
            if ret is not None:
                beat_returns.append(ret)
        elif color in ("big_miss", "miss"):
            misses.append(item)
            if ret is not None:
                miss_returns.append(ret)
        elif color == "inline":
            inline_count.append(item)

    quarters_with_eps = [q for q in items if q.get("eps_surprise_pct") is not None]
    total = len(quarters_with_eps)

    return {
        "quarters_with_eps_data": total,
        "beat_count": len(beats),
        "miss_count": len(misses),
        "inline_count": len(inline_count),
        "beat_rate_pct": round(len(beats) / total * 100) if total else None,
        "avg_beat_post5d_pct": round(float(sum(beat_returns) / len(beat_returns)), 2) if beat_returns else None,
        "avg_miss_post5d_pct": round(float(sum(miss_returns) / len(miss_returns)), 2) if miss_returns else None,
    }
