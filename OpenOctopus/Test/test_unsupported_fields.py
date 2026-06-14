import os
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test")

from app import app
from services.dashboard.summary import build_dashboard_summary
from services.portfolio.overview import build_portfolio_overview


@patch("services.dashboard.summary.get_analyst_estimates")
@patch("services.dashboard.summary.get_market_analyst_snapshot")
@patch("services.dashboard.summary.get_market_quote")
@patch("services.dashboard.summary.get_key_financials")
@patch("services.dashboard.summary.build_commitment_context")
def test_build_dashboard_summary_marks_supported_and_unsupported_fields(
    mock_commitment_context,
    mock_financials,
    mock_quote,
    mock_analyst,
    mock_estimates,
):
    mock_quote.return_value = {"symbol": "AAPL", "source": "yahoo", "price": 200.0, "fetched_at": "2026-04-20 20:00 UTC"}
    mock_analyst.return_value = {
        "source": "yahoo",
        "fetched_at": "2026-04-20 20:01 UTC",
        "target_upside_pct": 10.0,
        "current_recommendation": {
            "period": "0m",
            "strong_buy": 4,
            "buy": 6,
            "hold": 2,
            "sell": 0,
            "strong_sell": 0,
            "score": 83,
        },
        "recommendation_trend": [
            {"period": "0m", "score": 83},
            {"period": "-1m", "score": 80},
            {"period": "-2m", "score": 78},
            {"period": "-3m", "score": 76},
        ],
        "price_targets": {"mean": 220.0},
    }
    mock_estimates.return_value = {
        "quarters": [
            {"date": "2025-01-30", "eps_actual": 6.0, "eps_surprise_pct": 2.0, "revenue_surprise_pct": None},
            {"date": "2024-10-30", "eps_actual": 4.0, "eps_surprise_pct": -1.0, "revenue_surprise_pct": None},
            {"date": "2024-07-30", "eps_actual": 5.0, "eps_surprise_pct": 1.5, "revenue_surprise_pct": None},
            {"date": "2024-04-30", "eps_actual": 4.5, "eps_surprise_pct": 0.5, "revenue_surprise_pct": None},
            {"date": "2024-01-30", "eps_actual": 3.0, "eps_surprise_pct": 3.0, "revenue_surprise_pct": None},
        ]
    }
    mock_financials.return_value = {"eps_ttm": 12.4, "eps_forward": 14.1}
    mock_commitment_context.return_value = {
        "current_cached_transcript": None,
        "current_cached_transcript_error": "transcript_not_found",
        "current_fallback_transcript": {},
        "current_text": None,
        "previous_cached_transcript": None,
        "previous_fallback_transcript": None,
        "previous_text": None,
        "llm_commitment_analysis": {"error": "previous_quarter_transcript_missing"},
    }

    result = build_dashboard_summary("AAPL")

    assert result["trinity"]["realized_performance_score"]["status"] == "interim_solution"
    assert result["trinity"]["realized_performance_score"]["value"] == 100
    assert result["trinity"]["realized_performance_score"]["detail"]["eps_yoy_pct"] == 100.0
    assert result["trinity"]["guidance_vs_actuals_score"]["status"] == "interim_solution"
    assert result["trinity"]["analyst_consensus_score"]["status"] == "interim_solution"
    assert result["trinity_source_meta"][1]["source_generated_at"] == "2025-01-30"
    assert result["raw_data"]["earnings_power"][0]["value"] == 12.4
    assert result["raw_data"]["market_lens"][1]["value"] == 220.0
    assert result["macro_context"]["numeric_macro_claims"]["status"] == "no_available_data"


@patch("services.dashboard.summary.get_analyst_estimates")
@patch("services.dashboard.summary.get_market_analyst_snapshot")
@patch("services.dashboard.summary.get_market_quote")
@patch("services.dashboard.summary.get_key_financials")
@patch("services.dashboard.summary.build_commitment_context")
def test_build_dashboard_summary_uses_word_cloud_when_trinity_has_gap(
    mock_commitment_context,
    mock_financials,
    mock_quote,
    mock_analyst,
    mock_estimates,
):
    mock_quote.return_value = {"symbol": "AAPL", "source": "yahoo", "price": 200.0, "fetched_at": "2026-04-20 20:00 UTC"}
    mock_analyst.return_value = {"error": "analyst_data_unavailable", "source": "yahoo", "fetched_at": "2026-04-20 20:01 UTC"}
    mock_estimates.return_value = {
        "quarters": [
            {"date": "2025-01-30", "eps_actual": 6.0, "eps_surprise_pct": 2.0, "revenue_surprise_pct": None},
            {"date": "2024-10-30", "eps_actual": 4.0, "eps_surprise_pct": -1.0, "revenue_surprise_pct": None},
            {"date": "2024-07-30", "eps_actual": 5.0, "eps_surprise_pct": 1.5, "revenue_surprise_pct": None},
            {"date": "2024-04-30", "eps_actual": 4.5, "eps_surprise_pct": 0.5, "revenue_surprise_pct": None},
            {"date": "2024-01-30", "eps_actual": 3.0, "eps_surprise_pct": 3.0, "revenue_surprise_pct": None},
        ]
    }
    mock_financials.return_value = {"eps_ttm": 12.4, "eps_forward": 14.1}
    mock_commitment_context.return_value = {
        "current_cached_transcript": {
            "source": "hf_cached_transcripts",
            "date": "2025-01-30 16:30:00",
            "content_excerpt": "Current transcript",
        },
        "current_cached_transcript_error": None,
        "current_fallback_transcript": {},
        "current_text": "Current transcript",
        "previous_cached_transcript": {"content_excerpt": "Prior transcript"},
        "previous_fallback_transcript": None,
        "previous_text": "Prior transcript",
        "llm_commitment_analysis": {
            "t_minus_1_commitment_score": {
                "value": 77,
                "hard_commitments": [
                    {"statement": "We expect strong demand and margin expansion next quarter."},
                ],
                "forward_guidance": [
                    {"statement": "We remain confident in growth but cautious about macro weakness and tariff pressure."},
                ],
                "visionary_fluff": [],
            },
            "t_zero_mention_rate": {
                "value": 65,
                "matches": [],
            },
        },
    }

    result = build_dashboard_summary("AAPL")

    assert result["trinity"]["analyst_consensus_score"]["status"] == "no_available_data"
    assert result["trinity"]["alignment_trend_series"]["detail"]["render_mode"] == "alpha_beta_signals"
    assert result["trinity"]["alignment_trend_series"]["detail"]["source_generated_at"] == "2025-01-30 16:30:00"
    assert result["trinity"]["alignment_trend_series"]["value"]["positive_keywords"][0]["term"] in {"confident", "demand", "expansion", "growth", "strong", "scale", "margin", "operating"}
    assert result["trinity"]["alignment_trend_series"]["value"]["negative_keywords"][0]["term"] in {"cautious", "pressure", "weakness", "macro", "uncertainty", "tariff", "tariffs"}


def test_build_portfolio_overview_requires_inputs():
    result = build_portfolio_overview()

    assert result["status"] == "input_required"
    assert result["summary_cards"]["total_aum"]["status"] == "unavailable"
    assert "cost basis" in result["required_inputs"]


@patch("app.build_dashboard_summary")
def test_dashboard_summary_endpoint_returns_payload(mock_build):
    mock_build.return_value = {"ticker": "AAPL"}
    client = app.test_client()

    response = client.get("/api/dashboard/summary?ticker=AAPL")

    assert response.status_code == 200
    assert response.get_json()["ticker"] == "AAPL"


def test_dashboard_summary_endpoint_requires_ticker():
    client = app.test_client()

    response = client.get("/api/dashboard/summary")

    assert response.status_code == 400
    assert response.get_json()["error"] == "ticker is required"


def test_portfolio_overview_endpoint_returns_input_required_shape():
    client = app.test_client()

    response = client.get("/api/portfolio/overview")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "input_required"
    assert payload["summary_cards"]["ytd_return"]["status"] == "unavailable"
