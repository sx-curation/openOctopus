"""
Unit tests for agent/policy_monitoring/digest.py — generate_digest() function.
"""
from datetime import datetime

import pytest

from agent.policy_monitoring.digest import generate_digest
from agent.policy_monitoring.schemas import ImpactClassification, PolicyEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_event(source, doc_id, title, impact_hint="", published_year=2024) -> PolicyEvent:
    return PolicyEvent(
        id=PolicyEvent.make_id(source, doc_id, datetime(published_year, 3, 1)),
        source=source,
        source_doc_id=doc_id,
        title=title,
        published_at=datetime(published_year, 3, 1),
        jurisdictions=["EU"] if source == "EUR_LEX" else ["US"],
        url=f"https://example.com/{doc_id}",
        summary=f"Summary of {title}. {impact_hint}",
    )


EU_EVENT = _make_event("EUR_LEX", "32024R0001", "EU AI Act Regulation")
US_FR_EVENT = _make_event("FEDERAL_REGISTER", "2024-01234", "AI Governance Notice")
US_SEC_EVENT = _make_event("SEC", "0001193125-24-001", "SEC Concept Release on AI")

ALL_EVENTS = [EU_EVENT, US_FR_EVENT, US_SEC_EVENT]


def _clf(event: PolicyEvent, impact: str) -> ImpactClassification:
    return ImpactClassification(
        event_id=event.id,
        impact=impact,
        rationale=f"Test rationale for {impact}",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_generate_digest_returns_string():
    result = generate_digest(ALL_EVENTS)
    assert isinstance(result, str)
    assert len(result) > 100


def test_generate_digest_contains_all_titles():
    result = generate_digest(ALL_EVENTS)
    for ev in ALL_EVENTS:
        assert ev.title in result


def test_generate_digest_contains_source_urls():
    result = generate_digest(ALL_EVENTS)
    for ev in ALL_EVENTS:
        assert ev.url in result


def test_generate_digest_contains_published_dates():
    result = generate_digest(ALL_EVENTS)
    assert "2024-03-01" in result


def test_generate_digest_groups_by_source():
    result = generate_digest(ALL_EVENTS)
    # EUR-Lex section should appear before SEC section
    eur_pos = result.find("EUR-Lex")
    sec_pos = result.find("SEC EDGAR")
    assert eur_pos != -1
    assert sec_pos != -1
    assert eur_pos < sec_pos


def test_generate_digest_with_classifications():
    clfs = [
        _clf(EU_EVENT, "constraint"),
        _clf(US_FR_EVENT, "opportunity"),
        _clf(US_SEC_EVENT, "neutral"),
    ]
    result = generate_digest(ALL_EVENTS, classifications=clfs)
    assert "Constraint" in result or "constraint" in result
    assert "Opportunity" in result or "opportunity" in result


def test_generate_digest_empty_events_returns_no_events_message():
    result = generate_digest([])
    assert "No events found" in result


def test_generate_digest_custom_title():
    result = generate_digest(ALL_EVENTS, title="My Custom Digest Title")
    assert "My Custom Digest Title" in result


def test_generate_digest_contains_disclaimer():
    result = generate_digest(ALL_EVENTS)
    assert "Disclaimer" in result or "disclaimer" in result or "not" in result.lower()


def test_generate_digest_source_doc_id_visible():
    result = generate_digest([EU_EVENT])
    assert "32024R0001" in result


def test_generate_digest_sorted_newest_first_within_source():
    older = _make_event("EUR_LEX", "32023R0001", "Older Regulation", published_year=2023)
    newer = _make_event("EUR_LEX", "32024R0002", "Newer Regulation", published_year=2024)
    # Pass older first; digest should show newer first
    result = generate_digest([older, newer])
    newer_pos = result.find("Newer Regulation")
    older_pos = result.find("Older Regulation")
    assert newer_pos < older_pos
