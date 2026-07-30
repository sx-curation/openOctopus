"""
Unit tests for tools/policy_sources/eurlex.py — normalize() function.
Uses fixtures; does NOT call real APIs.
"""
import pytest
from agent.policy_monitoring.schemas import PolicyEvent
from tools.policy_sources.eurlex import normalize
from tools.policy_sources.http_client import ValidationError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_SPARQL_RESPONSE = {
    "results": {
        "bindings": [
            {
                "work": {"type": "uri", "value": "http://publications.europa.eu/resource/cellar/abc123"},
                "celex": {"type": "literal", "value": "32024R0001"},
                "title": {"type": "literal", "value": "Regulation (EU) 2024/1 on Artificial Intelligence"},
                "date": {"type": "literal", "value": "2024-03-15",
                         "datatype": "http://www.w3.org/2001/XMLSchema#date"},
                "type": {"type": "uri", "value": "http://publications.europa.eu/resource/authority/resource-type/REG"},
            },
            {
                "work": {"type": "uri", "value": "http://publications.europa.eu/resource/cellar/def456"},
                "celex": {"type": "literal", "value": "32024L0002"},
                "title": {"type": "literal", "value": "Directive (EU) 2024/2 on Data Governance"},
                "date": {"type": "literal", "value": "2024-06-01",
                         "datatype": "http://www.w3.org/2001/XMLSchema#date"},
                "type": {"type": "uri", "value": "http://publications.europa.eu/resource/authority/resource-type/DIR"},
            },
        ]
    }
}

EMPTY_SPARQL_RESPONSE = {"results": {"bindings": []}}

MALFORMED_SPARQL_RESPONSE = {"error": "SPARQL parse error"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_normalize_returns_list_of_policy_events():
    events = normalize(VALID_SPARQL_RESPONSE)
    assert isinstance(events, list)
    assert len(events) == 2
    assert all(isinstance(e, PolicyEvent) for e in events)


def test_normalize_fields_populated_correctly():
    events = normalize(VALID_SPARQL_RESPONSE)
    reg = next(e for e in events if e.source_doc_id == "32024R0001")

    assert reg.source == "EUR_LEX"
    assert reg.title == "Regulation (EU) 2024/1 on Artificial Intelligence"
    assert reg.jurisdictions == ["EU"]
    assert reg.regulator == "European Commission"
    assert "eur-lex.europa.eu" in reg.url
    assert "32024R0001" in reg.url
    assert reg.published_at.year == 2024
    assert reg.published_at.month == 3


def test_normalize_id_is_deterministic():
    events1 = normalize(VALID_SPARQL_RESPONSE)
    events2 = normalize(VALID_SPARQL_RESPONSE)
    assert events1[0].id == events2[0].id


def test_normalize_empty_bindings_returns_empty_list():
    events = normalize(EMPTY_SPARQL_RESPONSE)
    assert events == []


def test_normalize_malformed_response_raises_validation_error():
    with pytest.raises(ValidationError):
        normalize(MALFORMED_SPARQL_RESPONSE)


def test_normalize_skips_rows_with_missing_required_fields():
    response = {
        "results": {
            "bindings": [
                {"celex": {"value": "32024R0001"}},  # missing title and date
                {
                    "celex": {"value": "32024R0002"},
                    "title": {"value": "Valid Title"},
                    "date": {"value": "2024-01-01"},
                    "type": {"value": "http://publications.europa.eu/resource/authority/resource-type/REG"},
                },
            ]
        }
    }
    events = normalize(response)
    assert len(events) == 1
    assert events[0].source_doc_id == "32024R0002"
