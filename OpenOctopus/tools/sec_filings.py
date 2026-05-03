"""
Fetches MD&A and Risk Factors excerpts from the most recent 10-K or 10-Q
via the edgartools library (free, uses SEC EDGAR directly).
"""
from config import settings

# Maps keyword hints used by callers → candidate doc attribute names to probe.
# Prevents _extract_section from checking irrelevant attrs (e.g. risk_factors
# when fetching the MD&A section).
_KW_TO_ATTRS: dict[str, list[str]] = {
    "mda": ["mda", "management_discussion"],
    "management": ["mda", "management_discussion"],
    "discussion": ["mda", "management_discussion"],
    "risk factor": ["risk_factors"],
    "risk": ["risk_factors"],
}


def get_sec_filing_summary(ticker: str, filing_type: str = "10-K") -> dict:
    """
    Returns MD&A excerpt (~3000 chars) and Risk Factors excerpt (~2000 chars)
    from the most recent 10-K or 10-Q for the given ticker.
    """
    ticker = ticker.upper()
    try:
        from edgar import Company, set_identity

        # EDGAR requires a user-agent string identifying the requester
        set_identity(settings.EDGAR_IDENTITY)

        company = Company(ticker)
        filings = company.get_filings(form=filing_type)

        if filings is None or len(filings) == 0:
            # Fallback: try 10-Q if 10-K was requested and nothing found
            if filing_type == "10-K":
                filings = company.get_filings(form="10-Q")
                if filings is None or len(filings) == 0:
                    return {
                        "error": "no_filings_found",
                        "ticker": ticker,
                        "filing_type": filing_type,
                    }
                filing_type = "10-Q (fallback)"

        filing = filings.latest(1)
        filing_date = str(getattr(filing, "filing_date", "unknown"))
        period = str(getattr(filing, "period_of_report", "unknown"))

        # Get the filing document object for section extraction
        try:
            doc = filing.obj()
        except Exception:
            doc = None

        mda_text = _extract_section(doc, filing, ["management", "discussion", "mda"])
        risk_text = _extract_section(doc, filing, ["risk factor"])

        return {
            "ticker": ticker,
            "filing_type": filing_type,
            "filing_date": filing_date,
            "period_of_report": period,
            "mda_excerpt": mda_text[:3000] if mda_text else "Not available",
            "risk_factors_excerpt": risk_text[:2000] if risk_text else "Not available",
        }

    except ImportError:
        return {
            "error": "edgartools_not_installed",
            "detail": "Run: pip install edgartools",
            "ticker": ticker,
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker, "filing_type": filing_type}


def _extract_section(doc, filing, keywords: list[str]) -> str:
    """
    Attempt to extract a named section from the filing document.
    Tries the structured doc object first, then falls back to raw text search.
    Only probes doc attributes that are relevant to the requested keywords.
    """
    # Build candidate attr list from keywords to avoid returning the wrong section
    candidate_attrs: list[str] = []
    seen: set[str] = set()
    for kw in keywords:
        for attr in _KW_TO_ATTRS.get(kw, []):
            if attr not in seen:
                seen.add(attr)
                candidate_attrs.append(attr)

    # Try structured section extraction via edgartools
    if doc is not None:
        try:
            for attr in candidate_attrs:
                section = getattr(doc, attr, None)
                if section and isinstance(section, str) and len(section) > 100:
                    return section
            # Try calling as a method
            if hasattr(doc, "get_section"):
                for kw in keywords:
                    try:
                        text = doc.get_section(kw)
                        if text and len(text) > 100:
                            return text
                    except Exception:
                        pass
        except Exception:
            pass

    # Fallback: search raw text of the filing
    try:
        raw = filing.text()
        if raw:
            lower = raw.lower()
            for kw in keywords:
                idx = lower.find(kw)
                if idx != -1:
                    # Return a window around the first match
                    start = max(0, idx - 100)
                    return raw[start: start + 5000]
    except Exception:
        pass

    return ""
