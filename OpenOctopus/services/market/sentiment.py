from data_sources.market.service import get_market_quote, get_market_history
from datetime import datetime, timezone


def build_market_sentiment() -> dict:
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    vix_quote = get_market_quote("^VIX")
    vix9d_quote = get_market_quote("^VIX9D")
    gold_history = get_market_history("GC=F", period="35d")

    # ── VIX signal ──────────────────────────────────────────────────────────────
    vix_value = vix_quote.get("price") if "error" not in vix_quote else None
    vix_score, vix_label = _vix_signal(vix_value)

    # ── VIX term structure signal (VIX9D / VIX ratio) ────────────────────────────
    # Backwardation (ratio > 1) = near-term fear spike = bearish sentiment
    # Contango (ratio < 1) = normal/calm = bullish sentiment
    vix9d_value = vix9d_quote.get("price") if "error" not in vix9d_quote else None
    ts_ratio = round(vix9d_value / vix_value, 3) if vix9d_value and vix_value else None
    ts_score, ts_label = _term_structure_signal(ts_ratio)

    # ── Gold 1-month signal ──────────────────────────────────────────────────────
    gold_score, gold_label, gold_change_pct = _gold_signal(gold_history)

    # ── Composite score (VIX 40%, VIX term structure 40%, Gold 20%) ──────────────
    components = [
        (vix_score, 0.4),
        (ts_score, 0.4),
        (gold_score, 0.2),
    ]
    available = [(s * w, w) for s, w in components if s is not None]
    if available:
        total_weight = sum(w for _, w in available)
        composite = round(sum(sw for sw, _ in available) / total_weight)
    else:
        composite = None

    return {
        "fetched_at": fetched_at,
        "composite_score": composite,
        "composite_label": _composite_label(composite),
        "signals": {
            "vix": {
                "value": round(vix_value, 2) if vix_value is not None else None,
                "score": vix_score,
                "label": vix_label,
            },
            "vix_term_structure": {
                "vix9d": round(vix9d_value, 2) if vix9d_value is not None else None,
                "vix": round(vix_value, 2) if vix_value is not None else None,
                "ratio": ts_ratio,
                "score": ts_score,
                "label": ts_label,
            },
            "gold": {
                "change_pct_1m": round(gold_change_pct, 2) if gold_change_pct is not None else None,
                "score": gold_score,
                "label": gold_label,
            },
        },
    }


# ── Signal helpers ────────────────────────────────────────────────────────────

def _vix_signal(vix: float | None) -> tuple[int | None, str]:
    if vix is None:
        return None, "unavailable"
    if vix < 12:
        return 0, "extreme_greed"
    if vix < 17:
        return 25, "greed"
    if vix < 24:
        return 50, "neutral"
    if vix < 32:
        return 75, "fear"
    return 100, "extreme_fear"


def _term_structure_signal(ratio: float | None) -> tuple[int | None, str]:
    """VIX9D/VIX ratio: >1.05 = backwardation (fear), <0.95 = contango (greed)."""
    if ratio is None:
        return None, "unavailable"
    if ratio > 1.10:
        return 100, "extreme_fear"
    if ratio > 1.05:
        return 75, "fear"
    if ratio > 0.95:
        return 50, "neutral"
    if ratio > 0.90:
        return 25, "greed"
    return 0, "extreme_greed"


def _gold_signal(history: dict) -> tuple[int | None, str, float | None]:
    if "error" in history or not history.get("bars"):
        return None, "unavailable", None

    bars = history["bars"]
    if len(bars) < 2:
        return None, "unavailable", None

    latest_close = bars[-1].get("close")
    month_ago_close = bars[0].get("close")

    if latest_close is None or month_ago_close is None or month_ago_close == 0:
        return None, "unavailable", None

    change_pct = (latest_close - month_ago_close) / month_ago_close * 100

    if change_pct > 3:
        return 100, "fear", change_pct
    if change_pct > -1:
        return 50, "neutral", change_pct
    return 0, "greed", change_pct


def _composite_label(score: int | None) -> str:
    if score is None:
        return "unavailable"
    if score <= 33:
        return "greed"
    if score <= 67:
        return "neutral"
    return "fear"


