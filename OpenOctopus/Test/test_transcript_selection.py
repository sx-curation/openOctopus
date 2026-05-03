from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from config import settings
from data_sources.transcripts.hf_cache import get_cached_transcript
from services.dashboard.commitment_analysis import build_commitment_context
from tools.earnings_transcript import _select_nearest_transcript_date


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_get_cached_transcript_defaults_to_nearest_available_date():
    with TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "transcripts.jsonl"
        _write_jsonl(
            cache_path,
            [
                '{"symbol":"AAPL","year":2025,"quarter":4,"date":"2025-12-31 16:30:00","content":"older nearest","structured_content":[]}',
                '{"symbol":"AAPL","year":2026,"quarter":1,"date":"2026-04-10 16:30:00","content":"closest","structured_content":[]}',
                '{"symbol":"AAPL","year":2026,"quarter":2,"date":"2026-08-01 16:30:00","content":"future farther","structured_content":[]}',
            ],
        )
        with patch.object(settings, "HF_TRANSCRIPTS_PATH", str(cache_path)), patch(
            "data_sources.transcripts.hf_cache._current_utc",
            return_value=datetime(2026, 4, 20, tzinfo=timezone.utc),
        ):
            result = get_cached_transcript("AAPL")

    assert result["year"] == 2026
    assert result["quarter"] == 1
    assert result["date"] == "2026-04-10 16:30:00"


def test_select_nearest_transcript_date_prefers_nearest_past_entry():
    with patch(
        "tools.earnings_transcript._current_utc",
        return_value=datetime(2026, 4, 20, tzinfo=timezone.utc),
    ):
        selected = _select_nearest_transcript_date(
            [
                {"year": 2025, "quarter": 4, "date": "2025-12-31 16:30:00"},
                {"year": 2026, "quarter": 1, "date": "2026-04-18 16:30:00"},
                {"year": 2026, "quarter": 2, "date": "2026-04-22 16:30:00"},
            ]
        )

    assert selected["year"] == 2026
    assert selected["quarter"] == 1


@patch("services.dashboard.commitment_analysis._score_commitments_with_llm")
@patch("services.dashboard.commitment_analysis.get_earnings_transcript")
@patch("services.dashboard.commitment_analysis.get_cached_transcript")
def test_build_commitment_context_uses_fallback_period_for_previous_lookup(
    mock_cached,
    mock_fallback,
    mock_score,
):
    mock_cached.side_effect = [
        {"error": "transcript_not_found", "ticker": "AAPL"},
        {
            "ticker": "AAPL",
            "year": 2024,
            "quarter": 1,
            "date": "2024-02-02 16:30:00",
            "content_excerpt": "Prior cached transcript",
            "source": "hf_cached_transcripts",
        },
    ]
    mock_fallback.side_effect = [
        {
            "ticker": "AAPL",
            "transcript_year": 2024,
            "transcript_quarter": 2,
            "transcript_date": "2024-05-02 16:30:00",
            "transcript_excerpt": "Current fallback transcript",
        },
        {
            "ticker": "AAPL",
            "transcript_year": 2024,
            "transcript_quarter": 1,
            "transcript_date": "2024-02-02 16:30:00",
            "transcript_excerpt": "Prior fallback transcript",
        },
    ]
    mock_score.return_value = {"status": "ok"}

    result = build_commitment_context("AAPL", {"quarters": [{"date": "2024-05-02"}]})

    assert result["current_text"] == "Current fallback transcript"
    assert result["previous_text"] == "Prior cached transcript"
    assert result["current_fallback_transcript"]["transcript_date"] == "2024-05-02 16:30:00"
    mock_cached.assert_any_call("AAPL", year=2024, quarter=1)
    mock_fallback.assert_any_call("AAPL", year=2024, quarter=1)
    mock_score.assert_called_once_with("AAPL", {"quarters": [{"date": "2024-05-02"}]}, "Prior cached transcript", "Current fallback transcript", lang="en")
