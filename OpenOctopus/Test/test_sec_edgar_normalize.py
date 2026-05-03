"""
Unit tests for tools/policy_sources/sec_edgar.py — normalize() function.
Uses fixtures; does NOT call real APIs.
"""
import pytest
from agent.policy_monitoring.schemas import PolicyEvent
from tools.policy_sources.sec_edgar import normalize
from tools.policy_sources.http_client import ValidationError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_EFTS_RESPONSE = {
    "hits": {
        "total": {"value": 2, "relation": "eq"},
        "hits": [
            {
                "_id": "0001193125-24-001234",
                "_score": 1.5,
                "_source": {
                    "entity_name": "SECURITIES AND EXCHANGE COMMISSION",
                    "file_date": "2024-02-20",
                    "form_type": "RULE",
                    "period_of_report": "2024-06-30",
                    "file_num": "S7-24-01",
                    "display_names": ["Securities and Exchange Commission"],
                },
            },
            {
                "_id": "0001193125-24-005678",
                "_score": 1.2,
                "_source": {
                    "entity_name": "SECURITIES AND EXCHANGE COMMISSION",
                    "file_date": "2024-03-10",
                    "form_type": "CONCEPT",
                    "period_of_report": "",
                    "file_num": "S7-24-02",
                    "display_names": ["Securities and Exchange Commission"],
                },
            },
        ],
    }
}

EMPTY_EFTS_RESPONSE = {
    "hits": {
        "total": {"value": 0, "relation": "eq"},
        "hits": [],
    }
}

MALFORMED_EFTS_RESPONSE = {"results": []}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_normalize_returns_list_of_policy_events():
    events = normalize(VALID_EFTS_RESPONSE)
    assert isinstance(events, list)
    assert len(events) == 2
    assert all(isinstance(e, PolicyEvent) for e in events)


def test_normalize_fields_populated_correctly():
    events = normalize(VALID_EFTS_RESPONSE)
    rule = next(e for e in events if e.source_doc_id == "0001193125-24-001234")

    assert rule.source == "SEC"
    assert rule.jurisdictions == ["US"]
    assert rule.regulator == "SEC"
    assert "RULE" in rule.title
    assert "sec.gov" in rule.url
    assert rule.published_at.year == 2024
    assert rule.published_at.month == 2


def test_normalize_effective_from_parsed_when_present():
    events = normalize(VALID_EFTS_RESPONSE)
    rule = next(e for e in events if e.source_doc_id == "0001193125-24-001234")
    assert rule.effective_from is not None
    assert rule.effective_from.year == 2024


def test_normalize_empty_period_gives_none_effective_from():
    events = normalize(VALID_EFTS_RESPONSE)
    concept = next(e for e in events if e.source_doc_id == "0001193125-24-005678")
    assert concept.effective_from is None


def test_normalize_empty_hits_returns_empty_list():
    events = normalize(EMPTY_EFTS_RESPONSE)
    assert events == []


def test_normalize_malformed_response_raises_validation_error():
    with pytest.raises(ValidationError):
        normalize(MALFORMED_EFTS_RESPONSE)


def test_normalize_id_is_deterministic():
    events1 = normalize(VALID_EFTS_RESPONSE)
    events2 = normalize(VALID_EFTS_RESPONSE)
    assert events1[0].id == events2[0].id


def test_normalize_summary_contains_form_type_and_entity():
    events = normalize(VALID_EFTS_RESPONSE)
    rule = events[0]
    assert "RULE" in rule.summary or "CONCEPT" in rule.summary
