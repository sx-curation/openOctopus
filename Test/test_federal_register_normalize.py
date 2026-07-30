"""
Unit tests for tools/policy_sources/federal_register.py — normalize() function.
Uses fixtures; does NOT call real APIs.
"""
import pytest
from agent.policy_monitoring.schemas import PolicyEvent
from tools.policy_sources.federal_register import normalize
from tools.policy_sources.http_client import ValidationError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_FR_RESPONSE = {
    "count": 2,
    "total_pages": 1,
    "results": [
        {
            "document_number": "2024-01234",
            "title": "Regulation of Artificial Intelligence Systems",
            "abstract": "This rule establishes requirements for AI systems used in financial services.",
            "publication_date": "2024-03-15",
            "effective_on": "2024-06-01",
            "html_url": "https://www.federalregister.gov/documents/2024/03/15/2024-01234/regulation-of-artificial-intelligence",
            "pdf_url": "https://www.federalregister.gov/documents/full_text/pdf/2024-01234.pdf",
            "agencies": [{"name": "Securities and Exchange Commission", "id": 1}],
            "type": "RULE",
            "topics": ["artificial intelligence", "financial services"],
        },
        {
            "document_number": "2024-05678",
            "title": "Proposed Rule: Digital Asset Custody Standards",
            "abstract": "Proposed standards for custody of digital assets by registered investment advisers.",
            "publication_date": "2024-04-01",
            "effective_on": None,
            "html_url": "https://www.federalregister.gov/documents/2024/04/01/2024-05678/digital-asset-custody",
            "pdf_url": None,
            "agencies": [{"name": "Securities and Exchange Commission", "id": 1}],
            "type": "PROPOSED_RULE",
            "topics": ["digital assets", "investment advisers"],
        },
    ],
}

EMPTY_FR_RESPONSE = {"count": 0, "total_pages": 0, "results": []}

MALFORMED_FR_RESPONSE = {"data": []}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_normalize_returns_list_of_policy_events():
    events = normalize(VALID_FR_RESPONSE)
    assert isinstance(events, list)
    assert len(events) == 2
    assert all(isinstance(e, PolicyEvent) for e in events)


def test_normalize_fields_populated_correctly():
    events = normalize(VALID_FR_RESPONSE)
    rule = next(e for e in events if e.source_doc_id == "2024-01234")

    assert rule.source == "FEDERAL_REGISTER"
    assert rule.title == "Regulation of Artificial Intelligence Systems"
    assert rule.jurisdictions == ["US"]
    assert rule.regulator == "SEC"
    assert "federalregister.gov" in rule.url
    assert rule.published_at.year == 2024
    assert rule.published_at.month == 3
    assert rule.effective_from is not None
    assert rule.effective_from.month == 6
    assert "ai systems" in rule.summary.lower() or "artificial intelligence" in rule.summary.lower()


def test_normalize_topics_extracted():
    events = normalize(VALID_FR_RESPONSE)
    rule = next(e for e in events if e.source_doc_id == "2024-01234")
    assert "artificial intelligence" in rule.topics


def test_normalize_pdf_url_as_fulltext():
    events = normalize(VALID_FR_RESPONSE)
    rule = next(e for e in events if e.source_doc_id == "2024-01234")
    assert rule.fulltext_url is not None
    assert ".pdf" in rule.fulltext_url


def test_normalize_null_effective_on_is_none():
    events = normalize(VALID_FR_RESPONSE)
    proposed = next(e for e in events if e.source_doc_id == "2024-05678")
    assert proposed.effective_from is None


def test_normalize_empty_results_returns_empty_list():
    events = normalize(EMPTY_FR_RESPONSE)
    assert events == []


def test_normalize_malformed_response_raises_validation_error():
    with pytest.raises(ValidationError):
        normalize(MALFORMED_FR_RESPONSE)


def test_normalize_id_is_deterministic():
    events1 = normalize(VALID_FR_RESPONSE)
    events2 = normalize(VALID_FR_RESPONSE)
    assert events1[0].id == events2[0].id
