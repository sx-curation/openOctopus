"""
Integration tests for PolicyMonitoringAgent.query_updates() with mocked HTTP.
Does NOT call real APIs.
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent.policy_monitoring import PolicyMonitoringAgent, PolicyEvent


# ---------------------------------------------------------------------------
# Fixtures — raw API responses
# ---------------------------------------------------------------------------

_EURLEX_RAW = {
    "results": {
        "bindings": [
            {
                "celex": {"value": "32024R1234"},
                "title": {"value": "EU AI Act Implementation Regulation"},
                "date": {"value": "2024-03-01"},
                "type": {"value": "http://publications.europa.eu/resource/authority/resource-type/REG"},
            }
        ]
    }
}

_FR_RAW = {
    "count": 1,
    "results": [
        {
            "document_number": "2024-99001",
            "title": "AI Governance Framework for Financial Institutions",
            "abstract": "This notice proposes AI governance standards for banks and credit unions.",
            "publication_date": "2024-04-10",
            "effective_on": None,
            "html_url": "https://www.federalregister.gov/documents/2024/04/10/2024-99001/ai-governance",
            "pdf_url": None,
            "agencies": [{"name": "Federal Reserve"}],
            "type": "NOTICE",
            "topics": ["artificial intelligence"],
        }
    ],
}

_SEC_RAW = {
    "hits": {
        "total": {"value": 1, "relation": "eq"},
        "hits": [
            {
                "_id": "0001193125-24-099001",
                "_source": {
                    "entity_name": "SEC",
                    "file_date": "2024-04-15",
                    "form_type": "CONCEPT",
                    "period_of_report": "",
                    "file_num": "S7-24-10",
                    "display_names": ["Securities and Exchange Commission"],
                },
            }
        ],
    }
}


# ---------------------------------------------------------------------------
# Helper: build agent with mocked HTTP and cache
# ---------------------------------------------------------------------------

def _make_agent_with_mocked_http(source_raw_map: dict) -> PolicyMonitoringAgent:
    """
    Build a PolicyMonitoringAgent where _fetch_source() returns
    pre-normalised events from provided fixture data.
    """
    agent = PolicyMonitoringAgent.__new__(PolicyMonitoringAgent)

    # Mock cache (always miss)
    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mock_cache.set.return_value = None
    agent._cache = mock_cache

    # Mock HTTP client (unused when _fetch_source is mocked)
    agent._client = MagicMock()

    # Patch _fetch_source to use fixture data
    from tools.policy_sources import eurlex, federal_register, sec_edgar

    def fake_fetch_source(source, keyword, from_str, to_str, limit):
        raw = source_raw_map.get(source, {"results": {"bindings": []}})
        if source == "EUR_LEX":
            return eurlex.normalize(raw)
        if source == "FEDERAL_REGISTER":
            return federal_register.normalize(raw)
        if source == "SEC":
            return sec_edgar.normalize(raw)
        return []

    agent._fetch_source = fake_fetch_source
    return agent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_query_updates_all_sources_returns_events():
    agent = _make_agent_with_mocked_http({
        "EUR_LEX": _EURLEX_RAW,
        "FEDERAL_REGISTER": _FR_RAW,
        "SEC": _SEC_RAW,
    })
    events = agent.query_updates("ALL", "AI", "2024-01-01", "2024-12-31")

    assert len(events) == 3
    sources = {e.source for e in events}
    assert sources == {"EUR_LEX", "FEDERAL_REGISTER", "SEC"}


def test_query_updates_jurisdiction_eu_filters_to_eurlex_only():
    agent = _make_agent_with_mocked_http({
        "EUR_LEX": _EURLEX_RAW,
        "FEDERAL_REGISTER": _FR_RAW,
        "SEC": _SEC_RAW,
    })
    events = agent.query_updates("EU", "AI", "2024-01-01", "2024-12-31")

    assert all(e.source == "EUR_LEX" for e in events)


def test_query_updates_jurisdiction_us_excludes_eurlex():
    agent = _make_agent_with_mocked_http({
        "EUR_LEX": _EURLEX_RAW,
        "FEDERAL_REGISTER": _FR_RAW,
        "SEC": _SEC_RAW,
    })
    events = agent.query_updates("US", "AI", "2024-01-01", "2024-12-31")

    assert all(e.source != "EUR_LEX" for e in events)


def test_query_updates_source_error_is_gracefully_skipped():
    """A failing source should not crash the whole query."""
    agent = _make_agent_with_mocked_http({})

    def bad_fetch(source, *args, **kwargs):
        if source == "EUR_LEX":
            raise ConnectionError("network down")
        return []

    agent._fetch_source = bad_fetch
    events = agent.query_updates("ALL", "AI", "2024-01-01", "2024-12-31")
    assert isinstance(events, list)  # didn't crash


def test_query_updates_sorted_newest_first():
    agent = _make_agent_with_mocked_http({
        "EUR_LEX": _EURLEX_RAW,
        "FEDERAL_REGISTER": _FR_RAW,
        "SEC": _SEC_RAW,
    })
    events = agent.query_updates("ALL", "AI", "2024-01-01", "2024-12-31")

    dates = [e.published_at for e in events]
    assert dates == sorted(dates, reverse=True)


def test_classify_impact_constraint_for_ban_keyword():
    agent = _make_agent_with_mocked_http({})
    event = PolicyEvent(
        id="abc123",
        source="SEC",
        source_doc_id="test-001",
        title="Ban on Crypto Derivatives Trading",
        published_at=datetime(2024, 3, 1),
        jurisdictions=["US"],
        url="https://example.com",
        summary="The SEC bans and prohibits all crypto derivatives trading by retail investors.",
    )
    clf = agent.classify_impact(event)
    assert clf.impact == "constraint"
    assert len(clf.constraint_signals) > 0


def test_classify_impact_opportunity_for_grant_keyword():
    agent = _make_agent_with_mocked_http({})
    event = PolicyEvent(
        id="def456",
        source="FEDERAL_REGISTER",
        source_doc_id="2024-00001",
        title="Federal Grant Program for AI Innovation",
        published_at=datetime(2024, 4, 1),
        jurisdictions=["US"],
        url="https://example.com",
        summary="New funding and incentive program to facilitate AI innovation in financial services.",
    )
    clf = agent.classify_impact(event)
    assert clf.impact == "opportunity"
