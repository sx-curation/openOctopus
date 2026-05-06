"""
Scans recent 8-K filings to surface material corporate events that affect the investment thesis:
  - Executive/director departures and appointments (Item 5.02)
  - M&A agreements and terminations (Item 1.01 / 1.02)
  - Capital allocation announcements — buybacks, special dividends (Item 8.01 / 7.01)
  - Policy responses, regulatory matters, restructuring (Item 2.05 / 8.01)
  - Other material disclosures (Item 7.01 / 8.01)

Uses edgartools (EDGAR) exclusively — no API key required.
"""
from config import settings
from utils.formatting import parse_item_string
from tools.base import BaseTool
from tools.resilience import retry_with_backoff, with_timeout

# ---------------------------------------------------------------------------
# Item classification map — 8-K item numbers → semantic categories
# ---------------------------------------------------------------------------
_ITEM_TO_CATEGORY = {
    "1.01": "ma_event",           # Entry into Material Definitive Agreement
    "1.02": "ma_event",           # Termination of Material Definitive Agreement
    "2.02": "earnings_results",   # Results of Operations
    "2.05": "restructuring",      # Costs / Exit Activities
    "5.02": "executive_change",   # Director/Officer Departure or Appointment
    "5.03": "governance",         # Charter/Bylaw Amendments
    "7.01": "material_news",      # Regulation FD Disclosure
    "8.01": "material_news",      # Other Events
}

_CAPALLOC_KEYWORDS = frozenset(
    [
        "repurchase", "buyback", "share repurchase", "stock repurchase",
        "dividend", "special dividend", "return of capital", "capital return",
        "share buyback", "open market repurchase",
    ]
)

_POLICY_KEYWORDS = frozenset(
    [
        "tariff", "sanction", "regulation", "regulatory", "antitrust",
        "export control", "ban", "restriction", "executive order",
        "department of justice", "ftc", "sec investigation", "subpoena",
        "government contract", "defense contract",
    ]
)


class Sec8kTool(BaseTool):
    """Fetch categorised recent 8-K events via edgartools."""

    name = "get_recent_8k_events"
    description = (
        "Returns categorised recent 8-K events (executive changes, M&A, capital allocation, "
        "policy/regulatory, restructuring) for a given ticker."
    )

    def execute(self, input: dict) -> dict:
        ticker = input.get("ticker", "")
        lookback_count = input.get("lookback_count", 20)
        if not ticker:
            return {"error": "ticker_required"}
        try:
            return retry_with_backoff(
                lambda: with_timeout(
                    lambda: _fetch_8k_events(ticker.upper(), lookback_count), seconds=45
                ),
                max_retries=3,
                backoff_base=1.0,
            )
        except Exception as exc:
            return {"error": str(exc), "ticker": ticker.upper()}


def _fetch_8k_events(ticker: str, lookback_count: int = 20) -> dict:
    """
    Returns categorised recent 8-K events for the given ticker.

    Parameters
    ----------
    ticker : str  Stock ticker symbol.
    lookback_count : int  Max recent 8-K filings to scan (default 20 ≈ 6–12 months).

    Returns a dict with: ticker, filings_scanned, events (dict of category → list of entries).
    """
    ticker = ticker.upper()

    try:
        from edgar import Company, set_identity

        set_identity(settings.EDGAR_IDENTITY)

        company = Company(ticker)
        filings_8k = company.get_filings(form="8-K")

        if not filings_8k or len(filings_8k) == 0:
            return {"error": "no_8k_filings", "ticker": ticker}

        events: dict = {
            "executive_changes": [],
            "ma_events": [],
            "capital_allocation": [],
            "policy_regulatory": [],
            "restructuring": [],
            "other_material": [],
        }

        scanned = 0
        for filing in filings_8k:
            if scanned >= lookback_count:
                break
            scanned += 1
            filing_date = str(filing.filing_date)

            try:
                doc = filing.obj()
                # doc.items is a list of strings e.g. ['Item 5.02', 'Item 9.01']
                item_names = getattr(doc, "items", []) or []
                sections = doc.sections  # Sections dict-like object

                for item_str in item_names:
                    # Convert "Item 5.02" → section key "item_502" and item number "5.02"
                    item_num, section_key = parse_item_string(item_str)
                    if item_num is None:
                        continue

                    # Skip exhibits (9.01) — they're just file attachments
                    if item_num.startswith("9."):
                        continue

                    # Get section text
                    text = _get_section_text(sections, section_key)
                    if not text or len(text) < 80:
                        continue

                    category = _ITEM_TO_CATEGORY.get(item_num, "other_material")

                    entry = {
                        "date": filing_date,
                        "item": item_str,
                        "excerpt": text[:1500],
                    }

                    text_lower = text.lower()
                    if category == "executive_change":
                        events["executive_changes"].append(entry)
                    elif category == "ma_event":
                        events["ma_events"].append(entry)
                    elif category == "restructuring":
                        events["restructuring"].append(entry)
                    elif category == "earnings_results":
                        pass  # handled by get_earnings_transcript
                    elif _mentions_capital_allocation(text_lower):
                        events["capital_allocation"].append(entry)
                    elif _mentions_policy(text_lower):
                        events["policy_regulatory"].append(entry)
                    elif category in ("material_news", "governance", "other_material"):
                        if len(text) > 200:
                            events["other_material"].append(entry)

            except Exception:
                continue

        # Cap to most recent entries per category
        caps = {
            "executive_changes": 5,
            "ma_events": 5,
            "capital_allocation": 5,
            "policy_regulatory": 4,
            "restructuring": 3,
            "other_material": 3,
        }
        for key, cap in caps.items():
            events[key] = events[key][:cap]

        return {
            "ticker": ticker,
            "filings_scanned": scanned,
            "events": events,
        }

    except ImportError:
        return {
            "error": "edgartools_not_installed",
            "detail": "Run: pip install edgartools",
            "ticker": ticker,
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_section_text(sections, section_key: str) -> str:
    """Safely get text for a section key from the Sections object."""
    try:
        section = sections.get(section_key)
        if section is None:
            return ""
        text = section.text()
        return str(text) if text else ""
    except Exception:
        return ""


def _mentions_capital_allocation(text_lower: str) -> bool:
    return any(kw in text_lower for kw in _CAPALLOC_KEYWORDS)


def _mentions_policy(text_lower: str) -> bool:
    return any(kw in text_lower for kw in _POLICY_KEYWORDS)


# ---------------------------------------------------------------------------
# Module-level singleton + backward-compatible wrapper
# ---------------------------------------------------------------------------
_tool_8k = Sec8kTool()


def get_recent_8k_events(ticker: str, lookback_count: int = 20) -> dict:
    """Backward-compatible wrapper around Sec8kTool.execute()."""
    return _tool_8k.execute({"ticker": ticker, "lookback_count": lookback_count})
