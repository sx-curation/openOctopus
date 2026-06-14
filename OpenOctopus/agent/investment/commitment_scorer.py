"""
commitment_scorer.py — Agent-layer LLM scoring for management commitments.

This module owns the LLM call for commitment analysis and adds JSON schema
validation so a bad model response surfaces a structured error dict rather than
silently crashing the dashboard.

Usage
-----
from agent.investment.commitment_scorer import score_commitments

result = score_commitments(
    ticker="AAPL",
    prev_transcript="...",
    curr_transcript="...",
    estimates={...},
    lang="en",
)
# result is always a dict; check result.get("error") for failures.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from config import settings
from config.management_scoring import build_management_scoring_prompt
from agent.llm_client import get_llm_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-module LLM cache  key = (ticker, date_str, prev_256, curr_256, lang)
# ---------------------------------------------------------------------------
_LLM_CACHE: dict[tuple, dict] = {}

# ---------------------------------------------------------------------------
# JSON schema (minimal — validates required top-level keys and types)
# ---------------------------------------------------------------------------
_EXPECTED_SCHEMA = {
    "type": "object",
    "required": ["t_minus_1_commitment_score", "t_zero_mention_rate"],
    "properties": {
        "t_minus_1_commitment_score": {"type": "object"},
        "t_zero_mention_rate": {"type": "object"},
    },
}

# Quality thresholds (mirrored from services/dashboard/commitment_analysis.py)
_TRANSCRIPT_KEYWORDS = (
    "we expect", "we delivered", "we saw", "guidance", "outlook", "revenue",
    "earnings per share", "margin", "growth", "quarter", "fiscal",
)
_MIN_TRANSCRIPT_CHARS = 800
_MIN_TRANSCRIPT_KEYWORDS = 3

_LANG_NAMES = {"de": "German", "zh": "Simplified Chinese"}


def score_commitments(
    ticker: str,
    prev_transcript: str | None,
    curr_transcript: str | None,
    estimates: dict,
    lang: str = "en",
) -> dict:
    """Score management commitments using the shared LLM client.

    Returns a dict.  On success the dict contains the scoring result
    (``t_minus_1_commitment_score``, ``t_zero_mention_rate``, etc.).
    On any failure the dict contains ``{"error": "<reason>", ...}``.

    The result is cached in-process by (ticker, actuals_date, transcript fingerprints, lang).
    """
    if not prev_transcript:
        return {"error": "previous_quarter_transcript_missing"}
    if not curr_transcript:
        return {"error": "current_quarter_transcript_missing"}
    if not _text_quality_ok(prev_transcript):
        return {"error": "previous_quarter_transcript_insufficient", "chars": len(prev_transcript)}
    if not _text_quality_ok(curr_transcript):
        return {"error": "current_quarter_transcript_insufficient", "chars": len(curr_transcript)}

    actuals = _latest_actual_snapshot(estimates)
    latest_quarter = actuals.get("latest_quarter")
    if not latest_quarter:
        return {"error": "current_quarter_actuals_missing"}

    cache_key = (
        ticker,
        str(latest_quarter.get("date")),
        prev_transcript[:256],
        curr_transcript[:256],
        lang or "en",
    )
    cached = _LLM_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        client = get_llm_client()
    except EnvironmentError as exc:
        return {"error": str(exc)}

    prompt = build_management_scoring_prompt(
        ticker=ticker,
        previous_excerpt=_smart_excerpt(prev_transcript, settings.TRANSCRIPT_MAX_CHARS),
        current_excerpt=_smart_excerpt(curr_transcript, settings.TRANSCRIPT_MAX_CHARS),
        actuals_snapshot=actuals,
    )

    lang_note = (
        f" Write all natural language text fields in {_LANG_NAMES[lang]}. "
        "Keep all enum values (outcome, direction, repeat_status, "
        "direction_consistency, topic_continuity, sentiment, metric) in English."
        if lang and lang != "en" and lang in _LANG_NAMES
        else ""
    )

    try:
        from openai import APITimeoutError
        response = client.chat.completions.create(
            model=settings.MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a disciplined earnings-call scoring engine. "
                        "Return valid JSON only. "
                        "Do not include markdown fences or commentary." + lang_note
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=2500,
            timeout=settings.API_TIMEOUT,
        )
    except APITimeoutError:
        return {"error": f"commitment_scorer: model timeout after {settings.API_TIMEOUT}s"}
    except Exception as exc:
        return {"error": f"commitment_scorer: llm_call_failed: {exc}"}

    raw_content = response.choices[0].message.content or ""
    parsed = _parse_and_validate(raw_content)
    if "error" not in parsed:
        _LLM_CACHE[cache_key] = parsed
    return parsed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_and_validate(content: str) -> dict:
    """Extract JSON from *content* and validate against _EXPECTED_SCHEMA.

    Returns the parsed dict on success, or ``{"error": ..., "raw": content}``
    on any parse / validation failure.
    """
    try:
        json_str = _extract_json_object(content)
        parsed = json.loads(json_str)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("commitment_scorer: JSON parse failed: %s", exc)
        return {
            "error": f"commitment_scorer: invalid_json: {exc}",
            "raw": content[:500],
        }

    schema_error = _validate_schema(parsed)
    if schema_error:
        logger.warning("commitment_scorer: schema validation failed: %s", schema_error)
        return {
            "error": f"commitment_scorer: llm_response_schema_invalid: {schema_error}",
            "raw": content[:500],
        }

    return parsed


def _extract_json_object(content: str) -> str:
    """Extract the first ``{...}`` block from *content*, handling markdown fences."""
    # Try stripping markdown code fences first
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fence_match:
        return fence_match.group(1)

    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found in model output (len={len(content)})")
    return content[start : end + 1]


def _validate_schema(data: Any) -> str | None:
    """Lightweight schema check without jsonschema dependency.

    Returns an error message string on failure, or None on success.
    """
    if not isinstance(data, dict):
        return f"expected dict, got {type(data).__name__}"
    for required_key in _EXPECTED_SCHEMA["required"]:
        if required_key not in data:
            return f"missing required key: '{required_key}'"
        prop_type = _EXPECTED_SCHEMA["properties"][required_key]["type"]
        if prop_type == "object" and not isinstance(data[required_key], dict):
            return (
                f"'{required_key}' must be an object, "
                f"got {type(data[required_key]).__name__}"
            )
    return None


def _text_quality_ok(text: str | None) -> bool:
    if not text or len(text) < _MIN_TRANSCRIPT_CHARS:
        return False
    lower = text.lower()
    hits = sum(1 for kw in _TRANSCRIPT_KEYWORDS if kw in lower)
    return hits >= _MIN_TRANSCRIPT_KEYWORDS


def _latest_actual_snapshot(estimates: dict) -> dict:
    quarters = sorted(
        [item for item in estimates.get("quarters", []) if item.get("date")],
        key=lambda item: item["date"],
        reverse=True,
    )
    latest = quarters[0] if quarters else None
    prior_year = quarters[4] if len(quarters) >= 5 else None

    eps_yoy_pct = revenue_yoy_pct = None
    if latest and prior_year:
        latest_eps = latest.get("eps_actual")
        prior_eps = prior_year.get("eps_actual")
        if latest_eps is not None and prior_eps not in (None, 0):
            eps_yoy_pct = round(((latest_eps - prior_eps) / abs(prior_eps)) * 100, 2)
        latest_revenue = latest.get("revenue_actual")
        prior_revenue = prior_year.get("revenue_actual")
        if latest_revenue is not None and prior_revenue not in (None, 0):
            revenue_yoy_pct = round(((latest_revenue - prior_revenue) / abs(prior_revenue)) * 100, 2)

    return {
        "latest_quarter": latest,
        "prior_year_same_quarter": prior_year,
        "eps_yoy_pct": eps_yoy_pct,
        "revenue_yoy_pct": revenue_yoy_pct,
    }


def _smart_excerpt(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n\n[...transcript middle omitted...]\n\n" + text[-half:]
