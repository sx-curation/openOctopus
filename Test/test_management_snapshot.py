import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test")

from app import app
from config import settings
from services.dashboard.management import build_management_snapshot


def _write_jsonl(path: Path, items: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item) + "\n")


@patch("services.dashboard.management.get_analyst_estimates")
@patch("services.dashboard.management.build_commitment_context")
def test_build_management_snapshot_uses_cached_transcript(mock_context, mock_estimates):
    mock_estimates.return_value = {"quarters": [{"eps_surprise_pct": 2.0}, {"eps_surprise_pct": -1.0}]}
    mock_context.return_value = {
        "current_cached_transcript": {
            "ticker": "AAPL",
            "source": "hf_cached_transcripts",
            "quarter": 2,
            "content_excerpt": "Prepared remarks and Q&A",
        },
        "current_cached_transcript_error": None,
        "current_fallback_transcript": {},
        "current_text": "Hello world and we delivered strong revenue.",
        "previous_cached_transcript": {"quarter": 1, "content_excerpt": "We expect gross margin to improve next quarter."},
        "previous_fallback_transcript": None,
        "previous_text": "We expect gross margin to improve next quarter.",
        "llm_commitment_analysis": {
            "t_minus_1_commitment_score": {
                "value": None,
                "rationale": "Prior hard commitments were mostly met.",
                "evidence": ["We expect gross margin to improve."],
                "hard_commitments": [{
                    "statement": "We expect gross margin to improve.",
                    "topic": "gross margin",
                    "verifiable": True,
                    "outcome": "met",
                    "comparison_basis": "Compared prior gross-margin commitment with current-quarter actuals.",
                    "actual_reference": "Current-quarter gross margin improved year over year.",
                }],
                "forward_guidance": [],
                "visionary_fluff": [],
            },
            "t_zero_mention_rate": {
                "value": None,
                "rationale": "Management revisited the same margin theme with aligned direction.",
                "evidence": ["As we said last quarter..."],
                "matches": [{
                    "topic": "gross margin",
                    "previous_statement": "We expect gross margin to improve.",
                    "current_reference": "margin improved",
                    "repeat_status": "updated",
                    "direction_consistency": "aligned",
                    "topic_continuity": "continued",
                    "sentiment": "positive",
                    "deviation_note": "Management kept the same direction and reported progress.",
                }],
            },
        },
    }
    with TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "transcripts.jsonl"
        _write_jsonl(cache_path, [
            {
                "symbol": "AAPL",
                "year": 2024,
                "quarter": 2,
                "date": "2024-05-02 16:30:00",
                "company_name": "Apple Inc.",
                "content": "Prepared remarks and Q&A",
                "structured_content": [{"speaker": "CEO", "text": "Hello world and we delivered strong revenue."}],
            },
            {
                "symbol": "AAPL",
                "year": 2024,
                "quarter": 1,
                "date": "2024-02-02 16:30:00",
                "company_name": "Apple Inc.",
                "content": "Prepared remarks and Q&A",
                "structured_content": [{"speaker": "CEO", "text": "We expect gross margin to improve next quarter."}],
            },
        ])

        with patch.object(settings, "HF_TRANSCRIPTS_PATH", str(cache_path)):
            result = build_management_snapshot("AAPL")

    assert result["raw_source_available"] is True
    assert result["score_available"] is True
    assert result["cached_transcript"]["source"] == "hf_cached_transcripts"
    assert result["cached_transcript"]["quarter"] == 2
    assert result["heuristics"]["reliability_index"]["status"] == "interim_solution"
    assert result["heuristics"]["t_minus_1_commitment_score"]["status"] == "interim_solution"
    assert result["heuristics"]["t_minus_1_commitment_score"]["value"] is None
    assert result["heuristics"]["t_minus_1_commitment_score"]["detail"]["hard_commitments"][0]["outcome"] == "met"
    assert result["heuristics"]["t_zero_mention_rate"]["status"] == "interim_solution"
    assert result["heuristics"]["t_zero_mention_rate"]["value"] is None
    assert result["heuristics"]["t_zero_mention_rate"]["detail"]["matches"][0]["direction_consistency"] == "aligned"
    assert result["heuristics"]["transparency_score"]["status"] == "interim_solution"


@patch("services.dashboard.management.get_analyst_estimates")
@patch("services.dashboard.management.build_commitment_context")
def test_build_management_snapshot_surfaces_cache_miss(mock_context, mock_estimates):
    mock_estimates.return_value = {"quarters": []}
    mock_context.return_value = {
        "current_cached_transcript": None,
        "current_cached_transcript_error": "transcript_cache_missing",
        "current_fallback_transcript": {"transcript_error": "fmp_key_missing"},
        "current_text": None,
        "previous_cached_transcript": None,
        "previous_fallback_transcript": None,
        "previous_text": None,
        "llm_commitment_analysis": {"error": "previous_quarter_transcript_missing"},
    }

    with TemporaryDirectory() as tmpdir:
        missing_path = Path(tmpdir) / "missing.jsonl"
        with patch.object(settings, "HF_TRANSCRIPTS_PATH", str(missing_path)):
            result = build_management_snapshot("MSFT")

    assert result["cached_transcript"] is None
    assert result["cached_transcript_error"] == "transcript_cache_missing"
    assert result["score_available"] is False
    assert result["heuristics"]["reliability_index"]["status"] == "no_available_data"


@patch("app.build_management_snapshot")
def test_dashboard_management_endpoint_returns_snapshot(mock_build):
    mock_build.return_value = {"ticker": "AAPL", "score_available": False}
    client = app.test_client()

    response = client.get("/api/dashboard/management?ticker=AAPL")

    assert response.status_code == 200
    assert response.get_json()["ticker"] == "AAPL"


def test_dashboard_management_endpoint_requires_ticker():
    client = app.test_client()

    response = client.get("/api/dashboard/management")

    assert response.status_code == 400
    assert response.get_json()["error"] == "ticker is required"
