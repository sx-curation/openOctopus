import os
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test")

from app import app
from services.market.commodities import build_market_commodities
from services.market.sentiment import build_market_sentiment


# ── build_market_commodities ──────────────────────────────────────────────────

MOCK_QUOTE = {"symbol": "CL=F", "source": "yahoo", "price": 82.5, "change_pct": -0.8}
MOCK_HISTORY = {
    "symbol": "CL=F",
    "source": "yahoo",
    "bars": [
        {"date": f"2026-04-{10+i:02d}", "open": 80.0, "high": 83.0, "low": 79.0, "close": 80.0 + i * 0.5}
        for i in range(10)
    ],
}


@patch("services.market.commodities.get_market_history")
@patch("services.market.commodities.get_market_quote")
def test_build_market_commodities_returns_two_cards(mock_quote, mock_history):
    mock_quote.return_value = MOCK_QUOTE
    mock_history.return_value = MOCK_HISTORY

    result = build_market_commodities()

    assert "cards" in result
    assert len(result["cards"]) == 2
    ids = [c["id"] for c in result["cards"]]
    assert "brent" in ids
    assert "gold" in ids


@patch("services.market.commodities.get_market_history")
@patch("services.market.commodities.get_market_quote")
def test_build_market_commodities_sparkline_capped_at_7(mock_quote, mock_history):
    mock_quote.return_value = MOCK_QUOTE
    mock_history.return_value = MOCK_HISTORY  # 10 bars → should be trimmed to 7

    result = build_market_commodities()

    for card in result["cards"]:
        assert len(card["sparkline_30d"]) <= 30


@patch("services.market.commodities.get_market_history")
@patch("services.market.commodities.get_market_quote")
def test_build_market_commodities_quote_error_marks_unavailable(mock_quote, mock_history):
    mock_quote.return_value = {"error": "ticker_not_found", "symbol": "CL=F"}
    mock_history.return_value = {"error": "history_unavailable"}

    result = build_market_commodities()

    for card in result["cards"]:
        assert card["status"] == "unavailable"
        assert card["sparkline_30d"] == []


@patch("app.build_market_commodities")
def test_market_commodities_endpoint_status_200(mock_build):
    mock_build.return_value = {"cards": []}
    client = app.test_client()

    response = client.get("/api/market/commodities")

    assert response.status_code == 200
    assert response.get_json() == {"cards": []}


# ── build_market_sentiment ────────────────────────────────────────────────────

def _mock_vix_quote(price):
    return {"symbol": "^VIX", "source": "yahoo", "price": price, "change_pct": 0.0}


MOCK_GOLD_HISTORY_FEAR = {
    "symbol": "GC=F",
    "source": "yahoo",
    "bars": [
        {"date": "2026-03-15", "close": 2000.0},
        {"date": "2026-04-15", "close": 2100.0},  # +5% → fear
    ],
}
MOCK_GOLD_HISTORY_GREED = {
    "symbol": "GC=F",
    "source": "yahoo",
    "bars": [
        {"date": "2026-03-15", "close": 2000.0},
        {"date": "2026-04-15", "close": 1960.0},  # -2% → greed
    ],
}


@patch("services.market.sentiment.get_market_history")
@patch("services.market.sentiment.get_market_quote")
def test_build_market_sentiment_returns_required_keys(mock_quote, mock_history):
    mock_quote.return_value = _mock_vix_quote(20.0)
    mock_history.return_value = MOCK_GOLD_HISTORY_GREED

    result = build_market_sentiment()

    assert "composite_score" in result
    assert "composite_label" in result
    assert "signals" in result
    assert "vix" in result["signals"]
    assert "vix_term_structure" in result["signals"]
    assert "gold" in result["signals"]
    assert "fetched_at" in result


@patch("services.market.sentiment.get_market_history")
@patch("services.market.sentiment.get_market_quote")
def test_vix_above_32_yields_extreme_fear(mock_quote, mock_history):
    mock_quote.return_value = _mock_vix_quote(35.0)
    mock_history.return_value = MOCK_GOLD_HISTORY_GREED

    result = build_market_sentiment()

    assert result["signals"]["vix"]["label"] == "extreme_fear"
    assert result["signals"]["vix"]["score"] == 100


@patch("services.market.sentiment.get_market_history")
@patch("services.market.sentiment.get_market_quote")
def test_vix_below_12_yields_extreme_greed(mock_quote, mock_history):
    mock_quote.return_value = _mock_vix_quote(10.0)
    mock_history.return_value = MOCK_GOLD_HISTORY_GREED

    result = build_market_sentiment()

    assert result["signals"]["vix"]["label"] == "extreme_greed"
    assert result["signals"]["vix"]["score"] == 0


@patch("services.market.sentiment.get_market_history")
@patch("services.market.sentiment.get_market_quote")
def test_gold_above_3pct_yields_fear(mock_quote, mock_history):
    mock_quote.return_value = _mock_vix_quote(18.0)
    mock_history.return_value = MOCK_GOLD_HISTORY_FEAR

    result = build_market_sentiment()

    assert result["signals"]["gold"]["label"] == "fear"
    assert result["signals"]["gold"]["score"] == 100
    assert result["signals"]["gold"]["change_pct_1m"] == 5.0


@patch("services.market.sentiment.get_market_history")
@patch("services.market.sentiment.get_market_quote")
def test_gold_below_minus1pct_yields_greed(mock_quote, mock_history):
    mock_quote.return_value = _mock_vix_quote(18.0)
    mock_history.return_value = MOCK_GOLD_HISTORY_GREED

    result = build_market_sentiment()

    assert result["signals"]["gold"]["label"] == "greed"
    assert result["signals"]["gold"]["score"] == 0


@patch("services.market.sentiment.get_market_history")
@patch("services.market.sentiment.get_market_quote")
def test_composite_score_in_valid_range(mock_quote, mock_history):
    mock_quote.return_value = _mock_vix_quote(20.0)
    mock_history.return_value = MOCK_GOLD_HISTORY_GREED

    result = build_market_sentiment()

    score = result["composite_score"]
    assert score is not None
    assert 0 <= score <= 100


@patch("services.market.sentiment.get_market_history")
@patch("services.market.sentiment.get_market_quote")
def test_composite_label_greed_when_score_low(mock_quote, mock_history):
    # VIX=10 (extreme greed, score=0), gold=-2% (greed, score=0) → composite ≈ 0 → greed
    mock_quote.return_value = _mock_vix_quote(10.0)
    mock_history.return_value = MOCK_GOLD_HISTORY_GREED

    result = build_market_sentiment()

    assert result["composite_label"] == "greed"


@patch("services.market.sentiment.get_market_history")
@patch("services.market.sentiment.get_market_quote")
def test_all_unavailable_signals_returns_none_composite(mock_quote, mock_history):
    mock_quote.return_value = {"error": "unavailable"}
    mock_history.return_value = {"error": "unavailable"}

    result = build_market_sentiment()

    assert result["composite_score"] is None
    assert result["composite_label"] == "unavailable"


@patch("app.build_market_sentiment")
def test_market_sentiment_endpoint_status_200(mock_build):
    mock_build.return_value = {"composite_score": 42, "composite_label": "neutral", "signals": {}}
    client = app.test_client()

    response = client.get("/api/market/sentiment")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["composite_score"] == 42
    assert payload["composite_label"] == "neutral"
