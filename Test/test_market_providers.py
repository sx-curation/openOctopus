from unittest.mock import patch

from data_sources.market.service import get_market_quote
from data_sources.market.stooq import get_quote as get_stooq_quote
from data_sources.market.stooq import normalize_symbol


def test_stooq_normalize_symbol_maps_supported_aliases():
    assert normalize_symbol("AAPL") == "aapl.us"
    assert normalize_symbol("^GSPC") == "^spx"
    assert normalize_symbol("^IXIC") == "^ndq"
    assert normalize_symbol("^VIX") == "^vix"
    assert normalize_symbol("^TNX") == "10us"


@patch("data_sources.market.stooq.requests.get")
def test_stooq_quote_parses_snapshot_csv(mock_get):
    mock_get.return_value.raise_for_status.return_value = None
    mock_get.return_value.text = "AAPL.US,2026-04-17,22:00:19,266.96,272.30,266.72,270.23,61436228,APPLE INC"

    result = get_stooq_quote("AAPL")

    assert result["source"] == "stooq"
    assert result["provider_symbol"] == "aapl.us"
    assert result["close"] == 270.23
    assert result["volume"] == 61436228


@patch("data_sources.market.service.stooq.get_quote")
@patch("data_sources.market.service.yahoo.get_quote")
def test_market_quote_falls_back_to_stooq(mock_yahoo_quote, mock_stooq_quote):
    mock_yahoo_quote.return_value = {"error": "yahoo down", "source": "yahoo", "symbol": "AAPL"}
    mock_stooq_quote.return_value = {
        "symbol": "AAPL",
        "source": "stooq",
        "provider_symbol": "aapl.us",
        "price": 270.23,
        "change_pct": None,
        "open": 266.96,
        "high": 272.30,
        "low": 266.72,
        "close": 270.23,
        "volume": 61436228,
        "currency": None,
        "as_of": "2026-04-17",
        "name": "APPLE INC",
    }

    result = get_market_quote("AAPL")

    assert result["source"] == "stooq"
    assert result["fallback_reason"] == "yahoo down"
