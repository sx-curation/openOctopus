"""Competitor Comparison service for the Financial Health tab.

Functions:
  get_peers(ticker)                         -> {ticker, peers, source}
  get_company_profile(tickers)              -> {ticker: profile_dict, ...}
  get_price_history(tickers, period="1y")   -> {ticker: [{date, close}, ...], ...}
  get_analyst_ratings(tickers)              -> {ticker: {buy, hold, sell, total, target_low, target_mean, target_high}, ...}
  get_competitor_fh_scores(tickers, cache_ref) -> {ticker: {total_score, group_scores, indicator_scores, error}, ...}
  get_linkedin_jobs(tickers, company_names) -> {ticker: {count, source}, ...}
  get_llm_business_diff(main_ticker, competitor_tickers, profiles) -> {summary, key_diffs, ai_generated}
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
import yfinance as yf
import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

_FMP_BASE = "https://financialmodelingprep.com/api"
_FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; OpenOctopus/1.0)"})

# ── helpers ────────────────────────────────────────────────────────────────

def _fmp_get(path: str, params: dict | None = None) -> Any:
    """Call FMP API endpoint; returns parsed JSON or raises."""
    url = f"{_FMP_BASE}{path}"
    p = {"apikey": settings.FMP_API_KEY}
    if params:
        p.update(params)
    resp = _SESSION.get(url, params=p, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _fmp_stable_get(path: str, params: dict | None = None) -> Any:
    """Call FMP stable API endpoint (post-Aug-2025 format); returns parsed JSON or raises."""
    url = f"{_FMP_STABLE_BASE}{path}"
    p = {"apikey": settings.FMP_API_KEY}
    if params:
        p.update(params)
    resp = _SESSION.get(url, params=p, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ── A-1 / A-2  get_peers ──────────────────────────────────────────────────

def get_peers(ticker: str) -> Dict[str, Any]:
    """Return up to 5 peer tickers for the given stock.

    Returns: {ticker, peers: [str], source: "fmp" | "yfinance" | "none"}
    """
    ticker = ticker.upper()

    # FMP stable /stock-peers
    try:
        data = _fmp_stable_get("/stock-peers", {"symbol": ticker})
        if isinstance(data, list) and data:
            peers = [p for p in data[0].get("peersList", []) if p and p != ticker][:5]
            if peers:
                return {"ticker": ticker, "peers": peers, "source": "fmp"}
    except Exception as e:
        logger.warning("FMP peers failed for %s: %s", ticker, e)

    # yfinance fallback: get industry, then use FMP screener for top market-cap peers
    try:
        info_full = yf.Ticker(ticker).info
        sector = info_full.get("sector", "")
        industry = info_full.get("industry", "")
        if industry or sector:
            screener_params = {
                "isEtfAndFund": "false",
                "limit": 10,
                "industry": industry or sector,
            }
            try:
                screen_data = _fmp_stable_get("/stock-screener", screener_params)
                if isinstance(screen_data, list) and screen_data:
                    peers = [s["symbol"] for s in screen_data if s.get("symbol") and s["symbol"] != ticker][:5]
                    if peers:
                        return {"ticker": ticker, "peers": peers, "source": "yfinance"}
            except Exception:
                pass
    except Exception as e:
        logger.warning("yfinance peers fallback failed for %s: %s", ticker, e)

    return {"ticker": ticker, "peers": [], "source": "none"}


# ── A-3 / A-4  get_company_profile ────────────────────────────────────────

def get_company_profile(tickers: List[str]) -> Dict[str, Any]:
    """Return profile dict for each ticker.

    Profile keys: companyName, sector, industry, description, fullTimeEmployees,
                  ipoDate, website, country, mktCap, currency, exchange
    """
    results: Dict[str, Any] = {}
    if not tickers:
        return results

    # FMP batch /profile/{AAPL,MSFT,...}
    batch = ",".join(t.upper() for t in tickers)
    fmp_profiles: Dict[str, Any] = {}
    try:
        data = _fmp_get(f"/v3/profile/{batch}")
        if isinstance(data, list):
            for item in data:
                sym = (item.get("symbol") or "").upper()
                if sym:
                    fmp_profiles[sym] = item
    except Exception as e:
        logger.warning("FMP profile batch failed: %s", e)

    for ticker in tickers:
        t = ticker.upper()
        fp = fmp_profiles.get(t, {})

        profile: Dict[str, Any] = {
            "companyName":        fp.get("companyName") or t,
            "sector":             fp.get("sector") or "",
            "industry":           fp.get("industry") or "",
            "description":        fp.get("description") or "",
            "fullTimeEmployees":  fp.get("fullTimeEmployees"),
            "ipoDate":            fp.get("ipoDate") or "",
            "website":            fp.get("website") or "",
            "country":            fp.get("country") or "",
            "mktCap":             fp.get("mktCap"),
            "currency":           fp.get("currency") or "USD",
            "exchange":           fp.get("exchangeShortName") or fp.get("exchange") or "",
            "error":              None,
        }

        # yfinance補漏 description
        if not profile["description"]:
            try:
                yf_info = yf.Ticker(t).info
                profile["description"] = yf_info.get("longBusinessSummary") or ""
                if not profile["sector"]:
                    profile["sector"] = yf_info.get("sector") or ""
                if not profile["industry"]:
                    profile["industry"] = yf_info.get("industry") or ""
                if not profile["fullTimeEmployees"]:
                    profile["fullTimeEmployees"] = yf_info.get("fullTimeEmployees")
            except Exception as e:
                logger.debug("yfinance profile fallback failed for %s: %s", t, e)

        # If no name found at all, mark as not found but don't crash
        if not profile["companyName"] and not fp:
            profile["error"] = "not_found"

        results[t] = profile

    return results


# ── A-5 / A-6  get_price_history ──────────────────────────────────────────

def get_price_history(tickers: List[str], period: str = "1y") -> Dict[str, List[Dict]]:
    """Return close price history for each ticker.

    Returns: {ticker: [{date: "YYYY-MM-DD", close: float}, ...]}
    ⚠️ yf.download multi-ticker returns MultiIndex columns; single ticker returns plain.
    """
    results: Dict[str, List[Dict]] = {t.upper(): [] for t in tickers}
    if not tickers:
        return results

    unique = [t.upper() for t in tickers]
    try:
        df = yf.download(unique, period=period, auto_adjust=True, progress=False)
        if df.empty:
            return results

        # Normalize to a DataFrame where each column is a ticker
        if isinstance(df.columns, pd.MultiIndex):
            # Multi-ticker: columns are (Metric, Ticker)
            if "Close" in df.columns.get_level_values(0):
                closes = df["Close"]
            else:
                return results
        else:
            # Single ticker: plain columns
            if "Close" in df.columns:
                closes = df[["Close"]].rename(columns={"Close": unique[0]})
            else:
                return results

        for ticker in unique:
            if ticker not in closes.columns:
                continue
            series = closes[ticker].dropna()
            results[ticker] = [
                {"date": idx.strftime("%Y-%m-%d"), "close": round(float(v), 4)}
                for idx, v in series.items()
                if pd.notna(v)
            ]
    except Exception as e:
        logger.warning("get_price_history failed: %s", e)

    return results


# ── A-7 / A-8  get_analyst_ratings ────────────────────────────────────────

def get_analyst_ratings(tickers: List[str]) -> Dict[str, Any]:
    """Return analyst recommendation counts + price targets for each ticker.

    Returns: {ticker: {buy, hold, sell, total, target_low, target_mean, target_high}}
    """
    results: Dict[str, Any] = {}
    one_year_ago = datetime.utcnow() - timedelta(days=365)

    for ticker in tickers:
        t = ticker.upper()
        buy = hold = sell = 0
        target_low = target_mean = target_high = None

        # FMP analyst recommendations
        try:
            recs = _fmp_get(f"/v3/analyst-stock-recommendations/{t}")
            if isinstance(recs, list):
                for r in recs:
                    try:
                        rec_date = datetime.strptime(r.get("date", "")[:10], "%Y-%m-%d")
                        if rec_date >= one_year_ago:
                            buy  += int(r.get("analystRatingsbuy",       0) or 0)
                            buy  += int(r.get("analystRatingsStrongBuy", 0) or 0)
                            hold += int(r.get("analystRatingsHold",      0) or 0)
                            sell += int(r.get("analystRatingsSell",      0) or 0)
                            sell += int(r.get("analystRatingsStrongSell",0) or 0)
                    except Exception:
                        continue
        except Exception as e:
            logger.debug("FMP analyst recs failed for %s: %s", t, e)

        # FMP price target consensus
        try:
            pt = _fmp_get(f"/v4/price-target-consensus", {"symbol": t})
            if isinstance(pt, list) and pt:
                item = pt[0]
                target_mean  = item.get("targetConsensus")
                target_high  = item.get("targetHigh")
                target_low   = item.get("targetLow")
        except Exception as e:
            logger.debug("FMP price target failed for %s: %s", t, e)

        # yfinance fallback if targets still missing
        if target_mean is None:
            try:
                yf_info = yf.Ticker(t).info
                target_mean  = yf_info.get("targetMeanPrice")
                target_high  = yf_info.get("targetHighPrice")
                target_low   = yf_info.get("targetLowPrice")
                # Fallback recommendation counts
                if buy == hold == sell == 0:
                    nb = int(yf_info.get("numberOfAnalystOpinions") or 0)
                    rec_key = (yf_info.get("recommendationKey") or "").lower()
                    if rec_key in ("buy", "strong_buy"):
                        buy = nb
                    elif rec_key in ("sell", "strong_sell"):
                        sell = nb
                    elif rec_key == "hold":
                        hold = nb
            except Exception as e:
                logger.debug("yfinance analyst fallback failed for %s: %s", t, e)

        total = buy + hold + sell
        results[t] = {
            "buy":          buy,
            "hold":         hold,
            "sell":         sell,
            "total":        total,
            "target_low":   float(target_low)  if target_low  is not None else None,
            "target_mean":  float(target_mean) if target_mean is not None else None,
            "target_high":  float(target_high) if target_high is not None else None,
        }

    return results


# ── A-9 / A-10  get_competitor_fh_scores ──────────────────────────────────

def get_competitor_fh_scores(
    tickers: List[str],
    cache_ref: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute FH Score for each ticker in parallel, using existing cache.

    ⚠️ cache_ref must be passed in from app.py (_fh_data_cache) to avoid circular import.
    Returns: {ticker: {total_score, group_scores, indicator_scores, error}}
    """
    from services.financial_health.fetcher import fetch_financial_health
    from services.financial_health.scorer import score_financial_health

    _TIMEOUT = 15

    def _score_one(ticker: str) -> tuple[str, Dict]:
        t = ticker.upper()
        try:
            # Check cache first
            cached = cache_ref.get(t)
            if cached and (time.time() - cached.get("cached_at", 0)) < 1800:
                scoring = cached.get("scoring", {})
                return t, {
                    "total_score":       scoring.get("weighted_100"),
                    "group_scores":      scoring.get("group_scores"),
                    "indicator_scores":  scoring.get("indicator_scores"),
                    "error":             None,
                }

            raw = fetch_financial_health(t)
            if raw.get("error"):
                return t, {"total_score": None, "group_scores": None, "indicator_scores": None, "error": raw["error"]}

            scoring = score_financial_health(raw["fundamentals"])
            # Store in cache
            cache_ref[t] = {"payload": {}, "raw": raw, "scoring": scoring, "cached_at": time.time()}
            return t, {
                "total_score":      scoring.get("weighted_100"),
                "group_scores":     scoring.get("group_scores"),
                "indicator_scores": scoring.get("indicator_scores"),
                "error":            None,
            }
        except Exception as e:
            logger.warning("FH score failed for %s: %s", t, e)
            return t, {"total_score": None, "group_scores": None, "indicator_scores": None, "error": str(e)}

    results: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        future_map = {ex.submit(_score_one, t): t for t in tickers}
        try:
            for future in as_completed(future_map, timeout=_TIMEOUT * len(tickers)):
                try:
                    ticker_key, data = future.result(timeout=_TIMEOUT)
                    results[ticker_key] = data
                except FuturesTimeoutError:
                    t = future_map[future]
                    results[t.upper()] = {"total_score": None, "group_scores": None, "indicator_scores": None, "error": "timeout"}
                except Exception as e:
                    t = future_map[future]
                    results[t.upper()] = {"total_score": None, "group_scores": None, "indicator_scores": None, "error": str(e)}
        except FuturesTimeoutError:
            pass  # fall through — "Fill in missing" below handles remaining tickers

    # Fill in any tickers that didn't complete
    for t in tickers:
        if t.upper() not in results:
            results[t.upper()] = {"total_score": None, "group_scores": None, "indicator_scores": None, "error": "timeout"}

    return results


# ── A-11  get_linkedin_jobs ────────────────────────────────────────────────

def get_linkedin_jobs(tickers: List[str], company_names: Dict[str, str]) -> Dict[str, Any]:
    """Attempt to get LinkedIn job count for each company.

    ⚠️ LinkedIn almost always returns login intercept (302 or authwall in body).
    Always degrades gracefully to {count: null, source: "blocked"} or "unavailable".

    Returns: {ticker: {count, source}}
    """
    results: Dict[str, Any] = {}

    for ticker in tickers:
        t = ticker.upper()
        name = company_names.get(t) or t
        count = None
        source = "unavailable"

        try:
            url = f"https://www.linkedin.com/jobs/search/?keywords={requests.utils.quote(name)}&f_TPR=r2592000"
            resp = _SESSION.get(url, timeout=5, allow_redirects=True)

            # Detect login intercept
            final_url = resp.url or ""
            body = resp.text or ""
            if "/login" in final_url or "/authwall" in final_url or "authwall" in body[:2000]:
                source = "blocked"
            elif resp.status_code == 200:
                # Try to parse job count from page (fragile, best-effort)
                import re
                m = re.search(r"([\d,]+)\s+(?:jobs?|result)", body, re.IGNORECASE)
                if m:
                    count_str = m.group(1).replace(",", "")
                    count = int(count_str)
                    source = "linkedin"
                else:
                    source = "blocked"
            else:
                source = "unavailable"
        except Exception as e:
            logger.debug("LinkedIn jobs failed for %s (%s): %s", t, name, e)
            source = "unavailable"

        results[t] = {"count": count, "source": source}

    return results


# ── A-12  get_llm_business_diff ───────────────────────────────────────────

def get_llm_business_diff(
    main_ticker: str,
    competitor_tickers: List[str],
    profiles: Dict[str, Any],
) -> Dict[str, Any]:
    """Generate LLM summary of business differences between main company and competitors.

    Returns: {summary, key_diffs: [str], ai_generated: True, error?}
    """
    _NULL = {"summary": None, "key_diffs": [], "ai_generated": True}

    def _profile_snippet(t: str) -> str:
        p = profiles.get(t.upper(), {})
        name    = p.get("companyName") or t
        sector  = p.get("sector") or "Unknown sector"
        industry = p.get("industry") or ""
        emp     = p.get("fullTimeEmployees")
        emp_str = f"{emp:,}" if emp else "N/A"
        desc    = (p.get("description") or "")[:400]
        return f"{name} ({sector}/{industry}, {emp_str} employees): {desc}"

    try:
        from agent.llm_client import get_llm_client
        import json as _json

        main_snippet = _profile_snippet(main_ticker)
        comp_snippets = "\n".join(
            f"- {_profile_snippet(t)}" for t in competitor_tickers
        )

        prompt = (
            f"Main company:\n{main_snippet}\n\n"
            f"Competitors:\n{comp_snippets}\n\n"
            "Compare these companies. Return ONLY valid JSON: "
            '{"summary": "2-3 sentence overview of key business differences", '
            '"key_diffs": ["bullet 1", "bullet 2", "bullet 3"]} '
            "No markdown, no extra text."
        )

        client = get_llm_client()
        response = client.chat.completions.create(
            model=settings.MODEL,
            messages=[
                {"role": "system", "content": "You are a concise financial analyst. Return only JSON."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=400,
            temperature=0.3,
        )

        raw_text = response.choices[0].message.content or ""
        # Strip markdown code fences if present (handles ```json ... ``` and ``` ... ```)
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = lines[1:]  # drop opening fence line (```json or ```)
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]  # drop closing fence
            cleaned = "\n".join(lines).strip()

        parsed = _json.loads(cleaned)
        return {
            "summary":       parsed.get("summary") or "",
            "key_diffs":     parsed.get("key_diffs") or [],
            "ai_generated":  True,
        }

    except Exception as e:
        logger.warning("LLM business diff failed: %s", e)
        return {**_NULL, "error": "llm_unavailable"}
