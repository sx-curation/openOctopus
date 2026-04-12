"""
Fetches earnings call content from two complementary sources:
  1. EDGAR (primary)  — 8-K Item 2.02 earnings press release via edgartools (free, no key)
  2. FMP (secondary)  — full call transcript text (requires FMP_API_KEY)

Returns both where available so Claude can extract:
  - Key operating metrics (from press release numbers)
  - Management tone, guidance, competitive commentary (from transcript text)
"""
import requests
from config import settings
from utils.formatting import parse_item_string


def get_earnings_transcript(
    ticker: str,
    year: int | None = None,
    quarter: int | None = None,
) -> dict:
    ticker = ticker.upper()
    result: dict = {"ticker": ticker}

    # --- Primary: EDGAR 8-K earnings press release ---
    edgar_data = _get_edgar_earnings_release(ticker)
    result.update(edgar_data)

    # --- Secondary: FMP full call transcript ---
    if settings.FMP_API_KEY:
        fmp_data = _get_fmp_transcript(ticker, year, quarter)
        if "error" not in fmp_data:
            result["transcript_excerpt"] = fmp_data.get("transcript_excerpt")
            result["transcript_year"] = fmp_data.get("year")
            result["transcript_quarter"] = fmp_data.get("quarter")
            result["transcript_date"] = fmp_data.get("date")
            result["transcript_full_chars"] = fmp_data.get("full_length_chars")
            result["transcript_truncated"] = fmp_data.get("truncated")
            result["available_quarters"] = fmp_data.get("available_quarters", [])
        else:
            result["transcript_error"] = fmp_data.get("error")
    else:
        result["transcript_error"] = "fmp_key_missing — set FMP_API_KEY in .env for full call transcript"

    return result


# ---------------------------------------------------------------------------
# EDGAR helpers
# ---------------------------------------------------------------------------

def _get_edgar_earnings_release(ticker: str) -> dict:
    """
    Scan recent 8-K filings for an earnings press release (Item 2.02).
    Uses edgartools CurrentReport API: doc.items (list of strings), doc.sections.get(key).text().
    """
    try:
        from edgar import Company, set_identity
        set_identity(settings.EDGAR_IDENTITY)

        company = Company(ticker)
        filings_8k = company.get_filings(form="8-K")

        if not filings_8k or len(filings_8k) == 0:
            return {"edgar_error": "no_8k_filings_found"}

        for i, filing in enumerate(filings_8k):
            if i >= 12:
                break
            try:
                doc = filing.obj()

                # doc.items is a list of strings like ['Item 2.02', 'Item 9.01']
                item_names = getattr(doc, "items", []) or []
                has_202 = any("2.02" in s for s in item_names)

                if not has_202 and not getattr(doc, "has_earnings", False):
                    continue

                # Get Item 2.02 section text
                release_text = ""
                sections = doc.sections
                for item_str in item_names:
                    if "2.02" not in item_str:
                        continue
                    _, section_key = parse_item_string(item_str)
                    try:
                        section = sections.get(section_key)
                        if section:
                            release_text = section.text() or ""
                    except Exception:
                        pass

                # Also try the structured EarningsRelease summary for key metrics
                earnings_summary = ""
                try:
                    er = doc.earnings
                    if er:
                        earnings_summary = str(er.summary()) or ""
                except Exception:
                    pass

                combined = (release_text + "\n\n" + earnings_summary).strip()
                if combined:
                    return {
                        "earnings_release_date": str(filing.filing_date),
                        "earnings_release_excerpt": combined[:4000],
                    }

            except Exception:
                continue

        return {"edgar_error": "no_earnings_press_release_found_in_recent_8ks"}

    except ImportError:
        return {"edgar_error": "edgartools_not_installed — run: pip install edgartools"}
    except Exception as e:
        return {"edgar_error": str(e)}


# ---------------------------------------------------------------------------
# FMP helpers
# ---------------------------------------------------------------------------

def _get_fmp_transcript(ticker: str, year, quarter) -> dict:
    """Fetch full earnings call transcript from FMP API."""
    available_quarters: list = []

    if year is None or quarter is None:
        try:
            resp = requests.get(
                f"{settings.FMP_BASE_URL}/stable/earnings-transcript-dates"
                f"?symbol={ticker}&apikey={settings.FMP_API_KEY}",
                timeout=10,
            )
            if not resp.ok:
                return {"error": "fmp_dates_request_failed", "status_code": resp.status_code}
            dates_data = resp.json()
            if not dates_data:
                return {"error": "no_transcripts_available"}
            available_quarters = [
                {"year": d.get("year"), "quarter": d.get("quarter"), "date": d.get("date")}
                for d in dates_data
            ]
            most_recent = dates_data[0]
            year = most_recent.get("year")
            quarter = most_recent.get("quarter")
        except Exception as e:
            return {"error": str(e)}

    try:
        resp = requests.get(
            f"{settings.FMP_BASE_URL}/stable/earning-call-transcript"
            f"?symbol={ticker}&year={year}&quarter={quarter}&apikey={settings.FMP_API_KEY}",
            timeout=15,
        )
        if not resp.ok:
            return {"error": "transcript_fetch_failed", "status_code": resp.status_code}
        data = resp.json()
        if not data:
            return {"error": "transcript_empty", "available_quarters": available_quarters[:8]}

        item = data[0] if isinstance(data, list) else data
        full_text = item.get("content", "")
        full_length = len(full_text)

        return {
            "year": year,
            "quarter": quarter,
            "date": item.get("date"),
            "transcript_excerpt": full_text[: settings.TRANSCRIPT_MAX_CHARS],
            "full_length_chars": full_length,
            "truncated": full_length > settings.TRANSCRIPT_MAX_CHARS,
            "available_quarters": available_quarters[:8],
        }
    except Exception as e:
        return {"error": str(e)}
