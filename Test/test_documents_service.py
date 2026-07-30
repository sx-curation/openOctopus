import os
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test")

from app import app
from services.documents.recent_filings import build_recent_filings


@patch("services.documents.recent_filings.get_recent_8k_events")
@patch("services.documents.recent_filings.get_sec_filing_summary")
def test_build_recent_filings_returns_edgar_cards(mock_summary, mock_events):
    mock_summary.return_value = {
        "filing_type": "10-K",
        "filing_date": "2025-11-01",
        "period_of_report": "2025-09-30",
        "mda_excerpt": "Management discussion text.",
    }
    mock_events.return_value = {
        "events": {
            "other_material": [
                {"item": "Item 8.01", "date": "2025-10-20", "excerpt": "Material update."}
            ]
        }
    }

    result = build_recent_filings("AAPL")

    assert result["status"] == "ok"
    assert len(result["cards"]) == 2
    assert result["cards"][0]["form_type"] == "10-K"


@patch("app.build_recent_filings")
def test_recent_filings_endpoint_returns_payload(mock_build):
    mock_build.return_value = {"ticker": "AAPL", "cards": []}
    client = app.test_client()

    response = client.get("/api/documents/recent-filings?ticker=AAPL")

    assert response.status_code == 200
    assert response.get_json()["ticker"] == "AAPL"


def test_recent_filings_endpoint_requires_ticker():
    client = app.test_client()

    response = client.get("/api/documents/recent-filings")

    assert response.status_code == 400
    assert response.get_json()["error"] == "ticker is required"
