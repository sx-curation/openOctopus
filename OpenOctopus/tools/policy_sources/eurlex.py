"""
EUR-Lex adapter — queries EU legislation via the Publications Office SPARQL endpoint.

Endpoint: https://publications.europa.eu/webapi/rdf/sparql
Protocol: SPARQL 1.1 over HTTP GET, response format: application/sparql-results+json

CELEX number format examples:
  32024R0001  — Regulation (EU) 2024/1, adopted 2024
  32024L0001  — Directive (EU) 2024/1
  52024PC0001 — Proposal COM(2024) 1

Canonical URL pattern:
  https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from agent.policy_monitoring.schemas import PolicyEvent
from tools.policy_sources.http_client import ParseError, PolicyHttpClient, ValidationError

logger = logging.getLogger(__name__)

_SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
_CDM = "http://publications.europa.eu/ontology/cdm#"
_LANG_EN = "http://publications.europa.eu/resource/authority/language/ENG"

# Form types to include in queries
_DEFAULT_RESOURCE_TYPES = [
    "http://publications.europa.eu/resource/authority/resource-type/REG",       # Regulation
    "http://publications.europa.eu/resource/authority/resource-type/DIR",       # Directive
    "http://publications.europa.eu/resource/authority/resource-type/DEC",       # Decision
    "http://publications.europa.eu/resource/authority/resource-type/REC_BODY",  # Recommendation
    "http://publications.europa.eu/resource/authority/resource-type/NOTICE",    # Notice
]


def _build_search_query(
    keyword: str,
    from_date: str,
    to_date: str,
    limit: int,
    resource_types: list[str],
) -> str:
    type_values = " ".join(f"<{t}>" for t in resource_types)
    return f"""
PREFIX cdm: <{_CDM}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT DISTINCT ?work ?celex ?title ?date ?type
WHERE {{
  VALUES ?type {{ {type_values} }}
  ?work cdm:work_has_resource-type ?type .
  ?work cdm:work_date_document ?date .
  ?work cdm:work_id_document_sector ?celex .
  ?expr cdm:expression_belongs_to_work ?work .
  ?expr cdm:expression_title ?title .
  ?expr cdm:expression_uses_language <{_LANG_EN}> .
  FILTER(?date >= "{from_date}"^^xsd:date && ?date <= "{to_date}"^^xsd:date)
  FILTER(CONTAINS(LCASE(STR(?title)), LCASE("{keyword}")))
}}
ORDER BY DESC(?date)
LIMIT {limit}
""".strip()


def _sparql_result_to_event(row: dict[str, Any]) -> Optional[PolicyEvent]:
    """Convert a single SPARQL result row to a PolicyEvent."""
    try:
        celex = row.get("celex", {}).get("value", "")
        title = row.get("title", {}).get("value", "").strip()
        date_str = row.get("date", {}).get("value", "")
        type_uri = row.get("type", {}).get("value", "")

        if not celex or not title or not date_str:
            return None

        published_at = datetime.fromisoformat(date_str)
        url = f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"

        # Derive regulator from type URI
        type_label = type_uri.split("/")[-1] if type_uri else ""
        regulator_map = {
            "REG": "European Commission",
            "DIR": "European Commission",
            "DEC": "European Commission",
            "REC_BODY": "European Commission",
            "NOTICE": "European Commission",
        }
        regulator = regulator_map.get(type_label, "European Commission")

        event_id = PolicyEvent.make_id("EUR_LEX", celex, published_at)

        return PolicyEvent(
            id=event_id,
            source="EUR_LEX",
            source_doc_id=celex,
            title=title,
            published_at=published_at,
            jurisdictions=["EU"],
            regulator=regulator,
            topics=[],
            url=url,
            summary=f"{title} ({celex}). Published {date_str}. See full text at canonical URL.",
            fulltext_url=url,
            relationships={},
        )
    except Exception as exc:
        logger.warning("eurlex: failed to parse row %s: %s", row, exc)
        return None


# ---------------------------------------------------------------------------
# Public adapter API
# ---------------------------------------------------------------------------

def fetch_raw(
    client: PolicyHttpClient,
    keyword: str,
    from_date: str,
    to_date: str,
    limit: int = 20,
    resource_types: list[str] | None = None,
) -> dict:
    """
    Query the EUR-Lex SPARQL endpoint and return raw JSON response.

    Args:
        client: Shared PolicyHttpClient instance.
        keyword: Full-text search term.
        from_date: ISO date string "YYYY-MM-DD".
        to_date: ISO date string "YYYY-MM-DD".
        limit: Maximum number of results.
        resource_types: List of CDM resource type URIs to include.

    Returns:
        Raw SPARQL JSON results dict.

    Raises:
        NetworkError, RateLimitError, ParseError from http_client.
    """
    types = resource_types or _DEFAULT_RESOURCE_TYPES
    query = _build_search_query(keyword, from_date, to_date, limit, types)
    params = {
        "query": query,
        "format": "application/sparql-results+json",
    }
    return client.get_with_retry_on_ratelimit(
        _SPARQL_ENDPOINT,
        params=params,
        headers={"Accept": "application/sparql-results+json"},
    )


def normalize(raw: dict) -> list[PolicyEvent]:
    """
    Parse SPARQL JSON results into a list of PolicyEvent objects.

    Args:
        raw: Dict returned by fetch_raw().

    Returns:
        List of PolicyEvent (skips malformed rows silently, logs warnings).

    Raises:
        ValidationError: If the top-level SPARQL structure is unrecognisable.
    """
    try:
        bindings = raw["results"]["bindings"]
    except (KeyError, TypeError) as exc:
        raise ValidationError(
            f"EUR-Lex SPARQL response missing expected structure: {exc}\n"
            f"Keys present: {list(raw.keys()) if isinstance(raw, dict) else type(raw)}"
        ) from exc

    events: list[PolicyEvent] = []
    for row in bindings:
        ev = _sparql_result_to_event(row)
        if ev:
            events.append(ev)

    logger.debug("eurlex: normalised %d/%d rows", len(events), len(bindings))
    return events
