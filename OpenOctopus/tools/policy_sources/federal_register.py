"""
Federal Register adapter — queries the official US Federal Register API.

API docs: https://www.federalregister.gov/developers/api/v1
Endpoint: https://www.federalregister.gov/api/v1/documents.json
No API key required. Rate limit: respectful use (no stated limit).

Document types supported:
  RULE        — Final rules
  PROPOSED_RULE — Proposed rules (NPRM)
  NOTICE      — Agency notices and announcements
  PRESIDENTIAL_DOCUMENT — Executive orders, proclamations
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from agent.policy_monitoring.schemas import PolicyEvent
from agent.policy_monitoring.rules import normalize_regulator
from tools.policy_sources.http_client import ParseError, PolicyHttpClient, ValidationError

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.federalregister.gov/api/v1/documents.json"

_DEFAULT_DOC_TYPES = ["RULE", "PROPOSED_RULE", "NOTICE"]

_FIELDS = [
    "document_number",
    "title",
    "abstract",
    "publication_date",
    "effective_on",
    "html_url",
    "pdf_url",
    "agencies",
    "type",
    "topics",
    "cfr_references",
]


def fetch_raw(
    client: PolicyHttpClient,
    keyword: str,
    from_date: str,
    to_date: str,
    limit: int = 20,
    doc_types: list[str] | None = None,
) -> dict:
    """
    Fetch raw Federal Register search results.

    Args:
        client: Shared PolicyHttpClient.
        keyword: Full-text search term.
        from_date: "YYYY-MM-DD"
        to_date: "YYYY-MM-DD"
        limit: Max results (1–1000; API hard cap is 1000).
        doc_types: List of FR document type codes.

    Returns:
        Raw API JSON dict.
    """
    types = doc_types or _DEFAULT_DOC_TYPES
    params: dict[str, Any] = {
        "q": keyword,
        "per_page": min(limit, 1000),
        "order": "newest",
        "conditions[publication_date][gte]": from_date,
        "conditions[publication_date][lte]": to_date,
    }
    # Append array-style params manually (requests doesn't do [] syntax)
    for t in types:
        params.setdefault("conditions[type][]", [])
        if isinstance(params["conditions[type][]"], list):
            params["conditions[type][]"].append(t)
    for f in _FIELDS:
        params.setdefault("fields[]", [])
        if isinstance(params["fields[]"], list):
            params["fields[]"].append(f)

    return client.get_with_retry_on_ratelimit(_BASE_URL, params=params)


def _parse_date(s: str | None) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _extract_regulator(agencies: list[dict]) -> Optional[str]:
    if not agencies:
        return None
    names = [a.get("name", "") for a in agencies if a.get("name")]
    return normalize_regulator(names[0]) if names else None


def _fr_doc_to_event(doc: dict[str, Any]) -> Optional[PolicyEvent]:
    """Convert a single Federal Register document dict to PolicyEvent."""
    try:
        doc_num = doc.get("document_number", "")
        title = doc.get("title", "").strip()
        pub_date_str = doc.get("publication_date", "")
        html_url = doc.get("html_url", "")

        if not doc_num or not title or not pub_date_str:
            return None

        published_at = _parse_date(pub_date_str)
        if not published_at:
            return None

        effective_from = _parse_date(doc.get("effective_on"))
        abstract = (doc.get("abstract") or "").strip()
        summary = abstract[:500] if abstract else f"{title}. Published in Federal Register."

        agencies = doc.get("agencies") or []
        regulator = _extract_regulator(agencies)

        topics: list[str] = []
        for t in doc.get("topics") or []:
            if isinstance(t, str):
                topics.append(t)

        event_id = PolicyEvent.make_id("FEDERAL_REGISTER", doc_num, published_at)

        return PolicyEvent(
            id=event_id,
            source="FEDERAL_REGISTER",
            source_doc_id=doc_num,
            title=title,
            published_at=published_at,
            effective_from=effective_from,
            jurisdictions=["US"],
            regulator=regulator,
            topics=topics,
            url=html_url or f"https://www.federalregister.gov/d/{doc_num}",
            summary=summary,
            fulltext_url=doc.get("pdf_url"),
            relationships={},
        )
    except Exception as exc:
        logger.warning("federal_register: failed to parse doc %s: %s", doc.get("document_number"), exc)
        return None


# ---------------------------------------------------------------------------
# Public adapter API
# ---------------------------------------------------------------------------

def normalize(raw: dict) -> list[PolicyEvent]:
    """
    Parse Federal Register API response into PolicyEvent list.

    Raises:
        ValidationError: If the response is missing the 'results' key.
    """
    try:
        results = raw["results"]
    except (KeyError, TypeError) as exc:
        raise ValidationError(
            f"Federal Register response missing 'results' key: {exc}\n"
            f"Keys present: {list(raw.keys()) if isinstance(raw, dict) else type(raw)}"
        ) from exc

    events: list[PolicyEvent] = []
    for doc in results:
        ev = _fr_doc_to_event(doc)
        if ev:
            events.append(ev)

    logger.debug(
        "federal_register: normalised %d/%d results (total_count=%s)",
        len(events),
        len(results),
        raw.get("count", "?"),
    )
    return events
