import re

from tools.analyst_estimates import get_analyst_estimates
from config.management_scoring import SCORING_CONTRACT
from services.dashboard.commitment_analysis import build_commitment_context

_COMMITMENT_HINTS = ("will", "expect", "plan", "target", "guidance", "committed", "continue")
_HEDGE_HINTS = ("as i mentioned", "not going to", "cannot comment", "can't comment", "too early")
_STOPWORDS = {
    "about", "after", "again", "against", "analyst", "because", "before", "between", "could",
    "during", "earnings", "first", "forward", "great", "management", "margin", "quarter",
    "their", "there", "these", "those", "transcript", "while", "which", "would", "company",
}


def build_management_snapshot(
    ticker: str,
    year: int | None = None,
    quarter: int | None = None,
    lang: str = "en",
) -> dict:
    ticker = ticker.upper()
    estimates = get_analyst_estimates(ticker)
    commitment_context = build_commitment_context(ticker, estimates, year=year, quarter=quarter, lang=lang)
    cached = commitment_context["current_cached_transcript"]
    fallback = commitment_context["current_fallback_transcript"]
    previous_cached = commitment_context["previous_cached_transcript"]
    current_text = commitment_context["current_text"]
    previous_text = commitment_context["previous_text"]
    llm_commitment_analysis = commitment_context["llm_commitment_analysis"]

    raw_source_available = bool(cached) or bool(
        fallback.get("transcript_excerpt") or fallback.get("earnings_release_excerpt")
    )
    heuristics = _build_management_heuristics(estimates, previous_text, current_text, llm_commitment_analysis)

    methodology_note = (
        "interim solution — T-1 now shows an LLM completion checklist of prior-quarter commitments/guidance "
        "versus current-quarter actuals; T-0 now shows LLM topic continuity, directional consistency, and sentiment. "
        "transparency_score remains heuristic until full Azure management scoring ships."
    )
    if "error" in llm_commitment_analysis:
        methodology_note = (
            "interim solution — transcript retrieval is wired, but LLM commitment scoring is currently unavailable; "
            f"transparency_score remains heuristic. Commitment scoring detail: {llm_commitment_analysis['error']}."
        )

    return {
        "ticker": ticker,
        "requested_year": year,
        "requested_quarter": quarter,
        "raw_source_available": raw_source_available,
        "score_available": any(
            field["status"] == "interim_solution"
            for field in [
                heuristics["reliability_index"],
                heuristics["t_minus_1_commitment_score"],
                heuristics["t_zero_mention_rate"],
                heuristics["transparency_score"],
            ]
        ),
        "methodology": {
            "status": "interim_solution",
            "note": methodology_note,
            "contract": SCORING_CONTRACT,
        },
        "heuristics": heuristics,
        "llm_commitment_analysis": None if "error" in llm_commitment_analysis else llm_commitment_analysis,
        "llm_commitment_analysis_error": llm_commitment_analysis.get("error") if "error" in llm_commitment_analysis else None,
        "cached_transcript": cached,
        "cached_transcript_error": commitment_context["current_cached_transcript_error"],
        "previous_cached_transcript": previous_cached,
        "previous_fallback_transcript": commitment_context["previous_fallback_transcript"],
        "fallback_transcript": {
            "earnings_release_date": fallback.get("earnings_release_date"),
            "earnings_release_excerpt": fallback.get("earnings_release_excerpt"),
            "transcript_excerpt": fallback.get("transcript_excerpt"),
            "transcript_date": fallback.get("transcript_date"),
            "transcript_year": fallback.get("transcript_year"),
            "transcript_quarter": fallback.get("transcript_quarter"),
            "transcript_error": fallback.get("transcript_error"),
            "available_quarters": fallback.get("available_quarters"),
        },
        "_debug": commitment_context.get("_debug", {}),
    }


def _build_management_heuristics(
    estimates: dict,
    previous_text: str | None,
    current_text: str | None,
    llm_commitment_analysis: dict,
) -> dict:
    quarters_raw = estimates.get("quarters", [])
    eps_surprises = [
        item["eps_surprise_pct"]
        for item in quarters_raw
        if item.get("eps_surprise_pct") is not None
    ]
    beat_miss_history = [
        {"date": item.get("date"), "eps_surprise_pct": item.get("eps_surprise_pct")}
        for item in quarters_raw[:8]
    ]
    reliability = _no_available_data("Reliability index requires trailing earnings surprise history.")
    stddev = _no_available_data("Standard deviation requires trailing earnings surprise history.")
    if eps_surprises:
        avg = sum(eps_surprises) / len(eps_surprises)
        avg_abs = sum(abs(value) for value in eps_surprises) / len(eps_surprises)
        variance = sum((value - avg) ** 2 for value in eps_surprises) / len(eps_surprises)
        std_dev = variance ** 0.5
        reliability = _interim_solution(
            round(max(0, min(100, 100 - avg_abs * 4))),
            (
                "interim solution — using trailing EPS surprise consistency as a proxy "
                "for management reliability."
            ),
        )
        stddev = _interim_solution(
            round(std_dev, 2),
            "interim solution — standard deviation of trailing EPS surprise percentages.",
        )

    commitment = _no_available_data("Commitment checklist requires both transcript coverage and a configured LLM.")
    mention = _no_available_data("Topic continuity review requires both transcript coverage and a configured LLM.")
    transparency = _no_available_data("Transparency scoring requires a current transcript.")
    if "error" not in llm_commitment_analysis:
        commitment = _llm_structured_field(
            llm_commitment_analysis,
            "t_minus_1_commitment_score",
            (
                "interim solution — LLM classified prior-quarter hard commitments and forward guidance, "
                "then built a checklist against current-quarter actuals."
            ),
            ("hard_commitments", "forward_guidance"),
        )
        mention = _llm_structured_field(
            llm_commitment_analysis,
            "t_zero_mention_rate",
            (
                "interim solution — LLM compared prior-quarter commitments/guidance with the current-quarter "
                "transcript for same-topic direction consistency, continuity, and sentiment."
            ),
            ("matches",),
        )
    elif previous_text and current_text:
        commitment = _no_available_data(
            f"LLM commitment checklist unavailable: {llm_commitment_analysis['error']}",
            {"error": llm_commitment_analysis["error"]},
        )
        mention = _no_available_data(
            f"LLM topic continuity review unavailable: {llm_commitment_analysis['error']}",
            {"error": llm_commitment_analysis["error"]},
        )

    if current_text:
        text_lower = current_text.lower()
        direct = sum(text_lower.count(marker) for marker in ("we expect", "we delivered", "we saw", "our"))
        hedges = sum(text_lower.count(marker) for marker in _HEDGE_HINTS)
        analyst_cues = text_lower.count("question") + text_lower.count("analyst")
        raw_score = 5.0 + min(2.5, direct * 0.12 + analyst_cues * 0.04) - min(3.0, hedges * 0.4)
        transparency = _interim_solution(
            round(max(0.0, min(10.0, raw_score)), 1),
            (
                "interim solution — using direct-answer language, analyst Q&A density, and "
                "hedging cues as a transparency proxy."
            ),
        )

    return {
        "reliability_index": reliability,
        "std_dev_miss_beat": stddev,
        "t_minus_1_commitment_score": commitment,
        "t_zero_mention_rate": mention,
        "transparency_score": transparency,
        "beat_miss_history": beat_miss_history,
    }


def _llm_structured_field(
    payload: dict,
    field_name: str,
    fallback_rationale: str,
    signal_keys: tuple[str, ...],
) -> dict:
    field = payload.get(field_name, {})
    detail = {
        key: value
        for key, value in field.items()
        if key != "value"
    }
    has_signal = bool(field.get("rationale") or field.get("evidence") or any(field.get(key) for key in signal_keys))
    if not has_signal:
        return _no_available_data(field.get("rationale") or fallback_rationale, field)
    return _interim_solution(
        field.get("value"),
        field.get("rationale") or fallback_rationale,
        detail,
    )


def _no_available_data(rationale: str, detail: dict | None = None) -> dict:
    return {
        "status": "no_available_data",
        "label": "NO AVAILABLE DATA",
        "value": None,
        "rationale": rationale,
        "detail": detail or {},
    }


def _interim_solution(value, rationale: str, detail: dict | None = None) -> dict:
    return {
        "status": "interim_solution",
        "label": "interim solution",
        "value": value,
        "rationale": rationale,
        "detail": detail or {},
    }
