import os

os.environ.setdefault("OPENAI_API_KEY", "test")

from app import app
from config.ui_data_contracts import get_ui_data_contracts


def test_ui_contracts_exclude_policy_and_sentiment_surfaces():
    data = get_ui_data_contracts()

    excluded = set(data["scope"]["excluded_surfaces"])
    assert "dashboard.policy_outlook" in excluded
    assert "dashboard.sentiment_feed" in excluded


def test_ui_contracts_define_yahoo_stooq_split_for_market_cards():
    data = get_ui_data_contracts()
    sections = {section["id"]: section for section in data["sections"]}

    market = sections["market.overview_cards"]
    fields = {field["name"]: field for field in market["fields"]}
    assert fields["sp500"]["primary_source"] == "yahoo_finance"
    assert fields["sp500"]["fallback_source"] == "stooq"
    assert fields["vix"]["primary_source"] == "yahoo_finance"


def test_ui_contracts_mark_portfolio_aum_as_unavailable_without_inputs():
    data = get_ui_data_contracts()
    sections = {section["id"]: section for section in data["sections"]}

    portfolio = sections["portfolio.overview"]
    fields = {field["name"]: field for field in portfolio["fields"]}
    assert fields["total_aum"]["status"] == "unavailable"
    assert "cost basis" in fields["total_aum"]["rationale"].lower()


def test_ui_contracts_reflect_interim_and_no_data_states():
    data = get_ui_data_contracts()
    sections = {section["id"]: section for section in data["sections"]}

    trinity = {field["name"]: field for field in sections["dashboard.trinity_hero"]["fields"]}
    management = {field["name"]: field for field in sections["dashboard.management"]["fields"]}

    assert trinity["realized_performance_score"]["status"] == "interim_solution"
    assert trinity["guidance_vs_actuals_score"]["status"] == "interim_solution"
    assert management["transparency_score"]["status"] == "interim_solution"


def test_ui_contracts_endpoint_returns_contract_payload():
    client = app.test_client()
    response = client.get("/api/contracts/ui-data-sources")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["version"] == "1.0"
    assert any(endpoint["id"] == "dashboard.summary" for endpoint in payload["endpoints"])
