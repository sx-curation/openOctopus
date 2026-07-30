from tools.sec_8k_events import get_recent_8k_events
from tools.sec_filings import get_sec_filing_summary


def build_recent_filings(ticker: str) -> dict:
    ticker = ticker.upper()
    filing_summary = get_sec_filing_summary(ticker)
    event_summary = get_recent_8k_events(ticker)

    cards = []
    if "error" not in filing_summary:
        cards.append({
            "status": "ok",
            "form_type": filing_summary.get("filing_type", "10-K/10-Q"),
            "title": f"{ticker} {filing_summary.get('filing_type', '10-K/10-Q')} filing summary",
            "subtitle": (
                f"Filed {filing_summary.get('filing_date', 'unknown')} · "
                f"Period {filing_summary.get('period_of_report', 'unknown')}"
            ),
            "excerpt": filing_summary.get("mda_excerpt") or filing_summary.get("risk_factors_excerpt"),
            "source": "edgar",
        })

    if "error" not in event_summary:
        for card in _flatten_8k_events(event_summary.get("events", {}), ticker)[:3]:
            cards.append(card)

    if not cards:
        cards.append({
            "status": "no_available_data",
            "label": "NO AVAILABLE DATA",
            "form_type": "N/A",
            "title": f"{ticker} filings unavailable",
            "subtitle": "No EDGAR filing summary or material 8-K event data was available.",
            "excerpt": "NO AVAILABLE DATA",
            "source": "edgar",
        })

    return {
        "ticker": ticker,
        "status": "ok" if any(card["status"] == "ok" for card in cards) else "no_available_data",
        "cards": cards,
    }


def _flatten_8k_events(events: dict, ticker: str) -> list[dict]:
    labels = {
        "executive_changes": "8-K Executive Change",
        "ma_events": "8-K M&A Event",
        "capital_allocation": "8-K Capital Allocation",
        "policy_regulatory": "8-K Policy / Regulatory",
        "restructuring": "8-K Restructuring",
        "other_material": "8-K Material Event",
    }
    items = []
    for category, entries in events.items():
        for entry in entries:
            items.append({
                "status": "ok",
                "form_type": "8-K",
                "title": f"{ticker} {labels.get(category, '8-K Event')}",
                "subtitle": f"{entry.get('item', 'Item')} · Filed {entry.get('date', 'unknown')}",
                "excerpt": entry.get("excerpt"),
                "source": "edgar",
            })
    items.sort(key=lambda item: item["subtitle"], reverse=True)
    return items
