import json
from datetime import date
from typing import Any

from openai import APITimeoutError, AzureOpenAI, OpenAI

from config import settings
from config.management_scoring import build_management_scoring_prompt
from data_sources.transcripts.hf_cache import get_cached_transcript
from tools.earnings_transcript import get_earnings_transcript

_LLM_CACHE: dict[tuple[str, str | None, str | None, str | None], dict] = {}


def _infer_quarter_from_filing_date(filing_date_str: str | None) -> tuple[int, int] | tuple[None, None]:
    """Estimate fiscal year/quarter from an 8-K filing date.

    Earnings press releases are typically filed 0–75 days after the quarter ends:
      Q1 (Jan–Mar) → filed Apr–May
      Q2 (Apr–Jun) → filed Jul–Aug
      Q3 (Jul–Sep) → filed Oct–Nov
      Q4 (Oct–Dec) → filed Jan–Feb of following year
    """
    if not filing_date_str:
        return None, None
    try:
        fd = date.fromisoformat(str(filing_date_str)[:10])
    except (ValueError, TypeError):
        return None, None

    month = fd.month
    if month in (4, 5):
        return fd.year, 1
    elif month in (7, 8):
        return fd.year, 2
    elif month in (10, 11):
        return fd.year, 3
    elif month in (1, 2, 3):
        return fd.year - 1, 4
    # Edge months — best guess
    elif month == 6:
        return fd.year, 2
    elif month == 9:
        return fd.year, 3
    elif month == 12:
        return fd.year, 3
    return None, None


def build_commitment_context(
    ticker: str,
    estimates: dict,
    year: int | None = None,
    quarter: int | None = None,
    lang: str = "en",
) -> dict[str, Any]:
    ticker = ticker.upper()
    current_cached = get_cached_transcript(ticker, year=year, quarter=quarter)
    current_fallback = get_earnings_transcript(ticker, year=year, quarter=quarter)
    current_text = _current_transcript_text(current_cached, current_fallback)

    # Determine active year/quarter from best available source
    if "error" not in current_cached:
        active_year = current_cached.get("year")
        active_quarter = current_cached.get("quarter")
    else:
        active_year = current_fallback.get("transcript_year")
        active_quarter = current_fallback.get("transcript_quarter")
        # If FMP didn't supply year/quarter, infer from EDGAR filing date
        if active_year is None or active_quarter is None:
            active_year, active_quarter = _infer_quarter_from_filing_date(
                current_fallback.get("earnings_release_date")
            )

    previous_cached = _previous_cached_transcript(ticker, active_year, active_quarter)
    previous_fallback = _previous_fallback_transcript(
        ticker,
        active_year,
        active_quarter,
    )
    previous_text = _previous_transcript_text(previous_cached, previous_fallback)

    llm_commitment_analysis = _score_commitments_with_llm(ticker, estimates, previous_text, current_text, lang=lang)

    # Debug source metadata — surfaces what text was actually fed to the LLM
    def _text_source(cached: dict | None, fallback: dict | None) -> str:
        if cached:
            return f"hf_cache ({cached.get('content_chars', 0)} chars)"
        if fallback:
            if fallback.get("transcript_excerpt"):
                return f"fmp_transcript ({len(fallback.get('transcript_excerpt',''))} chars)"
            if fallback.get("earnings_release_excerpt"):
                return f"edgar_8k ({len(fallback.get('earnings_release_excerpt',''))} chars)"
        return "none"

    return {
        "current_cached_transcript": None if "error" in current_cached else current_cached,
        "current_cached_transcript_error": current_cached.get("error") if "error" in current_cached else None,
        "current_fallback_transcript": current_fallback,
        "current_text": current_text,
        "previous_cached_transcript": previous_cached,
        "previous_fallback_transcript": previous_fallback,
        "previous_text": previous_text,
        "llm_commitment_analysis": llm_commitment_analysis,
        "_debug": {
            "current_text_source": _text_source(
                None if "error" in current_cached else current_cached,
                current_fallback,
            ),
            "previous_text_source": _text_source(previous_cached, previous_fallback),
            "current_text_chars": len(current_text) if current_text else 0,
            "previous_text_chars": len(previous_text) if previous_text else 0,
            "llm_error": llm_commitment_analysis.get("error") if "error" in llm_commitment_analysis else None,
            "hf_cache_error": current_cached.get("error") if "error" in current_cached else None,
        },
    }


def _build_llm_client():
    if settings.AZURE_OPENAI_ENDPOINT:
        if not settings.AZURE_OPENAI_API_KEY:
            raise EnvironmentError("AZURE_OPENAI_ENDPOINT is set but AZURE_OPENAI_API_KEY is missing.")
        return AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )
    if not settings.OPENAI_API_KEY:
        raise EnvironmentError("OPENAI_API_KEY is missing for management LLM scoring.")
    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.BASE_URL or None,
    )


_TRANSCRIPT_KEYWORDS = (
    "we expect", "we delivered", "we saw", "guidance", "outlook", "revenue",
    "earnings per share", "margin", "growth", "quarter", "fiscal",
)
_MIN_TRANSCRIPT_CHARS = 800
_MIN_TRANSCRIPT_KEYWORDS = 3


def _text_quality_ok(text: str | None) -> bool:
    """Return True only if text has enough substance to be a real transcript/press release."""
    if not text or len(text) < _MIN_TRANSCRIPT_CHARS:
        return False
    lower = text.lower()
    hits = sum(1 for kw in _TRANSCRIPT_KEYWORDS if kw in lower)
    return hits >= _MIN_TRANSCRIPT_KEYWORDS


def _score_commitments_with_llm(
    ticker: str,
    estimates: dict,
    previous_text: str | None,
    current_text: str | None,
    lang: str = "en",
) -> dict:
    if not previous_text:
        return {"error": "previous_quarter_transcript_missing"}
    if not current_text:
        return {"error": "current_quarter_transcript_missing"}
    if not _text_quality_ok(previous_text):
        return {"error": "previous_quarter_transcript_insufficient", "chars": len(previous_text)}
    if not _text_quality_ok(current_text):
        return {"error": "current_quarter_transcript_insufficient", "chars": len(current_text)}

    actuals_snapshot = _latest_actual_snapshot(estimates)
    latest_quarter = actuals_snapshot.get("latest_quarter")
    if not latest_quarter:
        return {"error": "current_quarter_actuals_missing"}

    cache_key = (
        ticker,
        str(latest_quarter.get("date")),
        previous_text[:256],
        current_text[:256],
        lang or "en",
    )
    cached = _LLM_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        client = _build_llm_client()
    except EnvironmentError as exc:
        return {"error": str(exc)}

    prompt = build_management_scoring_prompt(
        ticker=ticker,
        previous_excerpt=_smart_excerpt(previous_text, settings.TRANSCRIPT_MAX_CHARS),
        current_excerpt=_smart_excerpt(current_text, settings.TRANSCRIPT_MAX_CHARS),
        actuals_snapshot=actuals_snapshot,
    )

    _LANG_NAMES = {"de": "German", "zh": "Simplified Chinese"}
    lang_note = (
        f" Write all natural language text fields (statement, rationale, evidence, "
        f"comparison_basis, actual_reference, deviation_note, previous_statement, current_reference) "
        f"in {_LANG_NAMES[lang]}. Keep all enum values (outcome, direction, repeat_status, "
        f"direction_consistency, topic_continuity, sentiment, metric) in English."
        if lang and lang != "en" and lang in _LANG_NAMES
        else ""
    )

    try:
        response = client.chat.completions.create(
            model=settings.MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a disciplined earnings-call scoring engine. Return valid JSON only. "
                        "Do not include markdown fences or commentary." + lang_note
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=2500,
            timeout=settings.API_TIMEOUT,
        )
    except APITimeoutError:
        return {"error": f"management scoring model timeout after {settings.API_TIMEOUT}s"}
    except Exception as exc:
        return {"error": str(exc)}

    content = response.choices[0].message.content or ""
    try:
        parsed = json.loads(_extract_json_object(content))
        _LLM_CACHE[cache_key] = parsed
        return parsed
    except json.JSONDecodeError as exc:
        return {"error": f"invalid_management_scoring_json: {exc}"}


def _latest_actual_snapshot(estimates: dict) -> dict:
    quarters = sorted(
        [item for item in estimates.get("quarters", []) if item.get("date")],
        key=lambda item: item["date"],
        reverse=True,
    )
    latest = quarters[0] if quarters else None
    prior_year = quarters[4] if len(quarters) >= 5 else None

    eps_yoy_pct = None
    revenue_yoy_pct = None
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


def _extract_json_object(content: str) -> str:
    content = content.strip()
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise json.JSONDecodeError("No JSON object found in model output.", content, 0)
    return content[start:end + 1]


def _previous_cached_transcript(ticker: str, year: int | None, quarter: int | None) -> dict | None:
    if year is None or quarter is None:
        return None

    previous_year, previous_quarter = _previous_period(year, quarter)
    previous = get_cached_transcript(ticker, year=previous_year, quarter=previous_quarter)
    if "error" in previous:
        return None
    return previous


def _previous_fallback_transcript(ticker: str, year: int | None, quarter: int | None) -> dict | None:
    if year is None or quarter is None:
        return None
    previous_year, previous_quarter = _previous_period(year, quarter)
    fallback = get_earnings_transcript(ticker, year=previous_year, quarter=previous_quarter)

    # Accept if FMP returned the exact quarter
    if fallback.get("transcript_year") == previous_year and fallback.get("transcript_quarter") == previous_quarter:
        return fallback

    # Also accept EDGAR earnings release that was tagged with the requested period
    if (
        fallback.get("edgar_year") == previous_year
        and fallback.get("edgar_quarter") == previous_quarter
        and fallback.get("earnings_release_excerpt")
    ):
        return fallback

    return None


def _previous_transcript_text(previous_cached: dict | None, previous_fallback: dict | None) -> str | None:
    if previous_cached:
        return previous_cached.get("content_excerpt")
    if previous_fallback:
        return previous_fallback.get("transcript_excerpt") or previous_fallback.get("earnings_release_excerpt")
    return None


def _current_transcript_text(cached: dict, fallback: dict) -> str | None:
    if "error" not in cached:
        return cached.get("content_excerpt")
    return fallback.get("transcript_excerpt") or fallback.get("earnings_release_excerpt")


def _previous_period(year: int, quarter: int) -> tuple[int, int]:
    previous_year = year
    previous_quarter = quarter - 1
    if previous_quarter <= 0:
        previous_year -= 1
        previous_quarter = 4
    return previous_year, previous_quarter


def _smart_excerpt(text: str, max_chars: int) -> str:
    """Extract a balanced excerpt: first half from start (prepared remarks), second half from end (Q&A)."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    head = text[:half]
    tail = text[-half:]
    return head + "\n\n[...transcript middle omitted...]\n\n" + tail
