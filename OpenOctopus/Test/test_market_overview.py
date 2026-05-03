import os
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test")

from app import app
from services.market.overview import build_market_overview


@patch("services.market.overview.get_market_quote")
def test_build_market_overview_returns_default_cards(mock_quote):
    mock_quote.return_value = {"symbol": "^GSPC", "source": "yahoo", "price": 5000.0, "change_pct": 1.2}

    result = build_market_overview()

    assert len(result["cards"]) == 3
    assert result["cards"][0]["id"] == "sp500"


@patch("app.build_market_overview")
def test_market_overview_endpoint_returns_payload(mock_build):
    mock_build.return_value = {"cards": []}
    client = app.test_client()

    response = client.get("/api/market/overview")

    assert response.status_code == 200
    assert response.get_json() == {"cards": []}
