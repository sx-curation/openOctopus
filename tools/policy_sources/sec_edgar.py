"""
SEC EDGAR adapter — queries SEC regulatory releases and rule filings.

Primary endpoint: EDGAR Full-Text Search (EFTS)
  https://efts.sec.gov/LATEST/search-index

IMPORTANT: All requests MUST include a User-Agent header identifying the application
and providing contact information, per SEC EDGAR policy:
  User-Agent: AppName/1.0 contact@example.com
Failure to include a valid User-Agent may result in 403 responses.

403 and 429 are handled with backoff retry in PolicyHttpClient.

Form types used for policy/regulatory monitoring:
  34-12G  — Form for small reporting companies
  EFFECT  — Effectiveness notices for registration statements
  No-Action Letter — Staff no-action guidance (informal)

For regulatory rule releases, the best source is the SEC's RSS/Atom feed:
  https://www.sec.gov/rules/proposed.shtml  (HTML, not API)
  https://www.sec.gov/rules/final.shtml

For MVP we use EFTS full-text search to find documents mentioning the keyword,
filtered to regulatory-relevant form types.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urljoin

from agent.policy_monitoring.schemas import PolicyEvent
from tools.policy_sources.http_client import PolicyHttpClient, ValidationError

logger = logging.getLogger(__name__)

_EFTS_BASE = "https://efts.sec.gov/LATEST/search-index"
_EDGAR_BASE = "https://www.sec.gov"

# Form types relevant for policy/regulatory monitoring
_DEFAULT_FORMS = ["S-1", "10-K", "8-K", "CORRESP", "UPLOAD"]

# Form types to prioritise — rule filings, concept releases, staff bulletins
_REGULATORY_FORMS = [
    "RULE",          # SEC final rules
    "CONCEPT",       # SEC concept releases
    "INTERP",        # Staff interpretive letters
    "NO-ACTION",     # No-action letters
    "34-12G",        # Reporting company determinations
]


def fetch_raw(
    client: PolicyHttpClient,
    keyword: str,
    from_date: str,
    to_date: str,
    limit: int = 20,
    forms: list[str] | None = None,
) -> dict:
    """
    Full-text search EDGAR for filings mentioning keyword within date range.

    Args:
        client: Shared PolicyHttpClient (must have SEC-compliant User-Agent set).
        keyword: Search term (supports quoted phrases: '"AI regulation"').
        from_date: "YYYY-MM-DD"
        to_date: "YYYY-MM-DD"
        limit: Max hits (up to 10 per EFTS page; use pagination for more).
        forms: List of SEC form type codes; defaults to regulatory forms.

    Returns:
        Raw EFTS JSON response dict.
    """
    form_list = forms or _REGULATORY_FORMS
    params: dict[str, Any] = {
        "q": f'"{keyword}"',
        "dateRange": "custom",
        "startdt": from_date,
        "enddt": to_date,
        "hits.hits.total.value": "true",
        "hits.hits._source": ",".join([
            "entity_name",
            "file_date",
            "form_type",
            "period_of_report",
            "file_num",
            "display_names",
        ]),
    }
    if form_list:
        params["forms"] = ",".join(form_list)

    return client.get_with_retry_on_ratelimit(_EFTS_BASE, params=params)


def _accession_to_url(accession: str, cik: str = "") -> str:
    """Convert accession number to EDGAR filing index URL."""
    clean = accession.replace("-", "")
    if cik:
        return f"https://www.sec.gov/Archives/edgar/data/{cik}/{clean}/0000000000-00-000000-index.htm"
    # Use EDGAR search URL as fallback
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={accession}"


def _hit_to_event(hit: dict[str, Any]) -> Optional[PolicyEvent]:
    """Convert a single EFTS search hit to PolicyEvent."""
    try:
        src = hit.get("_source", {})
        accession = hit.get("_id", "")
        entity = src.get("entity_name", src.get("display_names", ["Unknown"])[0] if isinstance(src.get("display_names"), list) else "Unknown")
        file_date_str = src.get("file_date", "")
        form_type = src.get("form_type", "")
        file_num = src.get("file_num", "")

        if not accession or not file_date_str:
            return None

        published_at = datetime.fromisoformat(file_date_str)
        period_str = src.get("period_of_report", "")
        effective_from = datetime.fromisoformat(period_str) if period_str else None

        # Build canonical URL
        # EDGAR viewer URL: https://www.sec.gov/Archives/edgar/data/CIK/ACCESSION-INDEX.htm
        accession_clean = accession.replace("-", "")
        url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={accession}&type={form_type}&dateb=&owner=include&count=1&search_text="
        # Better: use the direct filing URL
        edgar_url = f"https://www.sec.gov/Archives/edgar/data/0/{accession_clean}/{accession}-index.htm"

        title = f"{form_type}: {entity} ({file_date_str})"
        summary = (
            f"SEC {form_type} filing by {entity}, filed {file_date_str}. "
            f"Accession: {accession}. "
            + (f"File number: {file_num}." if file_num else "")
        )

        event_id = PolicyEvent.make_id("SEC", accession, published_at)

        return PolicyEvent(
            id=event_id,
            source="SEC",
            source_doc_id=accession,
            title=title,
            published_at=published_at,
            effective_from=effective_from,
            jurisdictions=["US"],
            regulator="SEC",
            topics=[],
            url=edgar_url,
            summary=summary,
            fulltext_url=f"https://efts.sec.gov/LATEST/search-index?q={accession}",
            relationships={},
        )
    except Exception as exc:
        logger.warning("sec_edgar: failed to parse hit %s: %s", hit.get("_id"), exc)
        return None


# ---------------------------------------------------------------------------
# Public adapter API
# ---------------------------------------------------------------------------

def normalize(raw: dict) -> list[PolicyEvent]:
    """
    Parse EFTS search response into PolicyEvent list.

    Raises:
        ValidationError: If the response is missing the expected EFTS structure.
    """
    try:
        hits = raw["hits"]["hits"]
        total = raw["hits"].get("total", {}).get("value", "?")
    except (KeyError, TypeError) as exc:
        raise ValidationError(
            f"SEC EDGAR EFTS response missing expected structure: {exc}\n"
            f"Keys present: {list(raw.keys()) if isinstance(raw, dict) else type(raw)}"
        ) from exc

    events: list[PolicyEvent] = []
    for hit in hits:
        ev = _hit_to_event(hit)
        if ev:
            events.append(ev)

    logger.debug(
        "sec_edgar: normalised %d/%d hits (total_matches=%s)",
        len(events),
        len(hits),
        total,
    )
    return events
