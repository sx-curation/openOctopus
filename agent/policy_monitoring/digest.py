"""
Markdown digest formatter for policy events.
Every item includes source URL and published date — all output is traceable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from agent.policy_monitoring.schemas import ImpactClassification, PolicyEvent

# Impact emoji / badge
_IMPACT_BADGE = {
    "opportunity": "🟢 Opportunity",
    "constraint": "🔴 Constraint",
    "neutral": "⚪ Neutral",
}

_IMPACT_BADGE_PLAIN = {
    "opportunity": "[OPPORTUNITY]",
    "constraint": "[CONSTRAINT]",
    "neutral":    "[NEUTRAL]",
}


def _fmt_date(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d") if dt else "N/A"


def _badge(impact: str, use_emoji: bool) -> str:
    if use_emoji:
        return _IMPACT_BADGE.get(impact, impact)
    return _IMPACT_BADGE_PLAIN.get(impact, impact)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_digest(
    events: List[PolicyEvent],
    classifications: Optional[List[ImpactClassification]] = None,
    title: str = "Policy Monitoring Digest",
    use_emoji: bool = True,
) -> str:
    """
    Render a list of PolicyEvents as a Markdown digest.
    Every item includes source URL and published date.

    Args:
        events: List of PolicyEvent objects.
        classifications: Optional parallel list of ImpactClassification objects.
        title: Report title string.
        use_emoji: Use emoji badges (True) or plain text tags (False).

    Returns:
        Markdown string.
    """
    if not events:
        return f"# {title}\n\n_No events found._\n"

    cls_map: dict[str, ImpactClassification] = {}
    if classifications:
        cls_map = {c.event_id: c for c in classifications}

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [
        f"# {title}",
        f"",
        f"> Generated: {now}  |  Events: {len(events)}",
        f"",
        "---",
        "",
    ]

    # Group by source
    by_source: dict[str, list[PolicyEvent]] = {}
    for ev in events:
        by_source.setdefault(ev.source, []).append(ev)

    source_labels = {
        "EUR_LEX": "🇪🇺 EUR-Lex (European Union)",
        "FEDERAL_REGISTER": "🇺🇸 Federal Register (United States)",
        "SEC": "🇺🇸 SEC EDGAR (United States)",
    }

    for source_key in ["EUR_LEX", "FEDERAL_REGISTER", "SEC"]:
        source_events = by_source.get(source_key, [])
        if not source_events:
            continue

        label = source_labels.get(source_key, source_key)
        lines.append(f"## {label}")
        lines.append("")

        for ev in sorted(source_events, key=lambda e: e.published_at, reverse=True):
            clf = cls_map.get(ev.id)

            # Header line
            badge = _badge(clf.impact, use_emoji) if clf else ""
            badge_str = f" — {badge}" if badge else ""
            lines.append(f"### {ev.title}{badge_str}")
            lines.append("")

            # Metadata table
            lines.append(f"| Field | Value |")
            lines.append(f"|-------|-------|")
            lines.append(f"| Source | `{ev.source}` |")
            lines.append(f"| Doc ID | `{ev.source_doc_id}` |")
            lines.append(f"| Published | {_fmt_date(ev.published_at)} |")
            lines.append(f"| Effective | {_fmt_date(ev.effective_from)} |")
            lines.append(f"| Jurisdiction | {', '.join(ev.jurisdictions)} |")
            if ev.regulator:
                lines.append(f"| Regulator | {ev.regulator} |")
            if ev.topics:
                lines.append(f"| Topics | {', '.join(ev.topics)} |")
            lines.append(f"| URL | [{ev.url}]({ev.url}) |")
            lines.append("")

            # Summary
            lines.append(f"**Summary:** {ev.summary}")
            lines.append("")

            # Impact rationale
            if clf:
                lines.append(f"**Signal:** {clf.rationale}")
                lines.append("")

            # Relationships
            if ev.relationships:
                rel_parts = []
                for rel_type, targets in ev.relationships.items():
                    rel_parts.append(f"_{rel_type}_: {', '.join(targets)}")
                lines.append("**Relationships:** " + "; ".join(rel_parts))
                lines.append("")

            lines.append("---")
            lines.append("")

    # Footer
    lines.append(
        "> **Disclaimer:** This digest contains policy monitoring signals only. "
        "It does not constitute legal or compliance advice. "
        "All entries include canonical source URLs for independent verification. "
        "MVP limitations: full-text not retrieved; diff depth limited to metadata."
    )

    return "\n".join(lines)
