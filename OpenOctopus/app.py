"""
OpenOctopus — Flask web server.

Serves the dashboard UI and exposes API endpoints backed by the
investment analysis agent (Azure / OpenAI-compatible).

Usage:
    python app.py          # starts on http://localhost:5000
"""
import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Ensure the app root is on sys.path so local packages (agent, config, etc.)
# are importable when gunicorn starts from a different working directory.
_app_root = Path(__file__).parent
if str(_app_root) not in sys.path:
    sys.path.insert(0, str(_app_root))

from flask import Flask, jsonify, request, send_file, send_from_directory
from flask.wrappers import Response

from agent import investment_run_analysis
from agent.policy_monitoring import PolicyMonitoringAgent
from config import settings
from data_sources.transcripts import hf_downloader
import utils.async_runner as async_runner
from config.ui_data_contracts import get_ui_data_contracts
from services.dashboard.earnings_cycle import build_earnings_cycle
from services.dashboard.management import build_management_snapshot
from services.dashboard.summary import build_dashboard_summary
from services.documents.recent_filings import build_recent_filings
from services.documents.library import build_document_library
from services.documents.analyzer import analyze_transcript as analyze_doc_transcript
from services.backlog.refresh import fetch_backlog_data
from services.backlog.search import search_ticker as backlog_search_ticker
from services.financial_health.fetcher import fetch_financial_health
from services.financial_health.scorer import score_financial_health, score_financial_health_multiyear
from services.financial_health.llm import health_summary as fh_health_summary, drilldown_analysis as fh_drilldown_analysis
from services.supply_chain.graph import discover_supply_chain as sc_discover
from services.supply_chain.analyzer import analyze_node as sc_analyze_node
from services.market.overview import build_market_overview
from services.market.commodities import build_market_commodities
from services.market.sentiment import build_market_sentiment
from services.portfolio.overview import build_portfolio_overview

# Taiwan services
from services.tw.dashboard.summary import build_dashboard_summary as tw_build_dashboard_summary
from services.tw.dashboard.summary import build_market_overview as tw_build_market_overview
from services.tw.dashboard.management import build_management_snapshot as tw_build_management_snapshot
from services.tw.documents.recent_announcements import build_recent_announcements
from services.tw.documents.financial_statements import build_financial_statements, build_annual_report_summary
from services.tw.market.overview import build_market_overview as tw_build_market_index

app = Flask(__name__, static_folder="UI", static_url_path="/static")

# Eagerly initialize LLM client at startup so provider detection runs with
# the correct env (avoids stale singleton from a previous process image).
from agent.llm_client import get_llm_client as _init_llm  # noqa: E402
_init_llm()
del _init_llm

UI_DIR = Path(__file__).parent / "UI"
_policy_agent = PolicyMonitoringAgent()


# ── UI ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index() -> Response:
    return send_from_directory(str(UI_DIR), "market-selector.html")


@app.route("/dashboard/us")
def dashboard_us() -> Response:
    html_path = str(UI_DIR / "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        }


@app.route("/dashboard/tw")
def dashboard_tw() -> Response:
    html_path = str(UI_DIR / "dashboard-tw.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        }


@app.route("/test")
def test_dashboard() -> Response:
    """Test dashboard with US/TW switcher"""
    html_path = str(UI_DIR / "test-dashboard.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


# ── Health ──────────────────────────────────────────────────────────────────

@app.route("/api/health")
def health() -> Response:
    backend = "azure" if settings.AZURE_OPENAI_ENDPOINT else "openai-compatible"
    return jsonify({
        "status": "ok",
        "backend": backend,
        "model": settings.MODEL,
        "base_url": settings.BASE_URL or "(default OpenAI)",
    })


# ── UI Data Contracts ────────────────────────────────────────────────────────

@app.route("/api/contracts/ui-data-sources")
def ui_data_sources() -> Response:
    return jsonify(get_ui_data_contracts())


# ── Dashboard Earnings Cycle ────────────────────────────────────────────────

@app.route("/api/dashboard/earnings-cycle")
def dashboard_earnings_cycle() -> Response:
    ticker = (request.args.get("ticker") or "").strip().upper()
    limit = int(request.args.get("limit", "3"))
    window_days = int(request.args.get("window_days", "5"))

    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    result = build_earnings_cycle(ticker, limit=limit, window_days=window_days)
    status_code = 200 if "error" not in result else 502
    return jsonify(result), status_code


@app.route("/api/dashboard/management")
def dashboard_management() -> Response:
    ticker = (request.args.get("ticker") or "").strip().upper()
    year = request.args.get("year", type=int)
    quarter = request.args.get("quarter", type=int)
    lang = (request.args.get("lang") or "en").strip().lower()

    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    result = build_management_snapshot(ticker, year=year, quarter=quarter, lang=lang)

    # 6-2: Transcript download orchestration.
    hf_error = result.get("cached_transcript_error")
    if hf_error == "transcript_cache_missing":
        # File is completely absent — kick off a background download and let the
        # frontend know so it can poll /api/transcripts/status.
        hf_downloader.trigger_background_download(ticker)
        result["transcript_downloading"] = True
    else:
        # Transcript file exists but LLM couldn't score (content too short / missing
        # previous quarter).  Not a download issue — surface to the UI differently.
        llm_err = result.get("llm_commitment_analysis_error") or ""
        if "insufficient" in llm_err or "missing" in llm_err:
            result["transcript_insufficient"] = True

    return jsonify(result)


@app.route("/api/debug/transcript")
def debug_transcript() -> Response:
    """Debug endpoint: shows what transcript sources are available for a ticker."""
    from pathlib import Path
    from data_sources.transcripts.hf_cache import get_cached_transcript
    from tools.earnings_transcript import get_earnings_transcript

    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    hf_path = Path(settings.HF_TRANSCRIPTS_PATH)
    hf_cache = get_cached_transcript(ticker)
    edgar_fallback = get_earnings_transcript(ticker)

    return jsonify({
        "ticker": ticker,
        "hf_cache_path": str(hf_path),
        "hf_cache_file_exists": hf_path.exists(),
        "hf_cache_file_size_mb": round(hf_path.stat().st_size / 1024 / 1024, 2) if hf_path.exists() else None,
        "hf_result_status": "ok" if "error" not in hf_cache else hf_cache.get("error"),
        "hf_content_chars": hf_cache.get("content_chars") if "error" not in hf_cache else 0,
        "edgar_has_release": bool(edgar_fallback.get("earnings_release_excerpt")),
        "edgar_release_chars": len(edgar_fallback.get("earnings_release_excerpt") or ""),
        "fmp_has_transcript": bool(edgar_fallback.get("transcript_excerpt")),
        "fmp_transcript_chars": len(edgar_fallback.get("transcript_excerpt") or ""),
        "fmp_transcript_error": edgar_fallback.get("transcript_error"),
        "fmp_key_set": bool(settings.FMP_API_KEY),
    })


@app.route("/api/transcripts/status")
def transcript_status() -> Response:
    """6-1: Poll the per-ticker HuggingFace transcript download status."""
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    return jsonify(hf_downloader.get_download_status(ticker))


@app.route("/api/dashboard/summary")
def dashboard_summary() -> Response:
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    return jsonify(build_dashboard_summary(ticker))


@app.route("/api/portfolio/overview")
def portfolio_overview() -> Response:
    return jsonify(build_portfolio_overview())


@app.route("/api/market/overview")
def market_overview() -> Response:
    symbols = [
        symbol.strip().upper()
        for symbol in (request.args.get("symbols") or "").split(",")
        if symbol.strip()
    ]
    return jsonify(build_market_overview(symbols or None))


@app.route("/api/market/commodities")
def market_commodities() -> Response:
    return jsonify(build_market_commodities())


@app.route("/api/market/sentiment")
def market_sentiment() -> Response:
    return jsonify(build_market_sentiment())


@app.route("/api/documents/recent-filings")
def documents_recent_filings() -> Response:
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    return jsonify(build_recent_filings(ticker))


@app.route("/api/documents/library")
def documents_library() -> Response:
    """Return all locally cached transcript entries for the Document Library tab."""
    return jsonify(build_document_library())


@app.route("/api/documents/analyze", methods=["POST"])
def documents_analyze() -> Response:
    """Analyze a transcript with LLM and return positive/negative signals."""
    body = request.get_json(silent=True) or {}
    ticker = (body.get("ticker") or "").strip().upper()
    lang = (body.get("lang") or "en").strip().lower()
    if lang not in ("en", "de", "zh"):
        lang = "en"
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400
    try:
        year = int(body["year"]) if body.get("year") is not None else None
        quarter = int(body["quarter"]) if body.get("quarter") is not None else None
    except (ValueError, TypeError):
        return jsonify({"error": "year and quarter must be integers"}), 400
    result = analyze_doc_transcript(ticker, year, quarter, lang)
    return jsonify(result)


# ── Backlog ─────────────────────────────────────────────────────────────────

@app.route("/api/backlog/refresh", methods=["POST"])
def backlog_refresh() -> Response:
    """Fetch live yfinance data for a list of backlog tickers."""
    body = request.get_json(silent=True) or {}
    tickers = body.get("tickers") or []
    # Validate: must be a list of non-empty strings, each ≤ 20 chars
    if not isinstance(tickers, list):
        return jsonify({"error": "tickers must be a list"}), 400
    tickers = [str(t).strip().upper() for t in tickers if str(t).strip()][:100]
    if not tickers:
        return jsonify({"items": []})
    return jsonify({"items": fetch_backlog_data(tickers)})


@app.route("/api/backlog/chips_batch", methods=["POST"])
def backlog_chips_batch() -> Response:
    """Fetch chips data (volume, short interest, options) for a list of backlog tickers."""
    from services.chips.volume import fetch_volume_data
    from services.chips.short_interest import fetch_short_interest
    from services.chips.options_flow import fetch_options_flow
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from concurrent.futures import TimeoutError as FuturesTimeoutError

    body = request.get_json(silent=True) or {}
    tickers = body.get("tickers") or []
    if not isinstance(tickers, list):
        return jsonify({"error": "tickers must be a list"}), 400
    tickers = [str(t).strip().upper() for t in tickers if str(t).strip()][:50]
    if not tickers:
        return jsonify({"items": []})

    results: dict = {}

    def _fetch(t: str):
        vol = fetch_volume_data(t)
        short = fetch_short_interest(t)
        opts = fetch_options_flow(t)
        return t, {
            "ticker": t,
            "rvol": vol.get("rvol"),
            "rvol_signal": vol.get("rvol_signal"),
            "price_vs_vwap_pct": vol.get("price_vs_vwap_pct"),
            "days_to_cover": short.get("days_to_cover"),
            "mom_change_pct": short.get("mom_change_pct"),
            "pcr_oi": opts.get("pcr_oi"),
            "error": vol.get("error") or short.get("error") or opts.get("error"),
        }

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_fetch, t): t for t in tickers}
        try:
            for fut in as_completed(futs, timeout=90):
                try:
                    t, data = fut.result()
                    results[t] = data
                except Exception as exc:
                    t = futs[fut]
                    results[t] = {"ticker": t, "error": str(exc)}
        except FuturesTimeoutError:
            pass

    items = [results.get(t, {"ticker": t, "error": "timeout"}) for t in tickers]
    return jsonify({"items": items})


@app.route("/api/backlog/search")
def backlog_search() -> Response:
    """Search for tickers by symbol or company name."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": []})
    return jsonify({"results": backlog_search_ticker(q)})

@app.route("/api/backlog/valuation/<ticker>")
def backlog_valuation(ticker: str) -> Response:
    """Compute predicted valuation prices for a ticker using yfinance TTM PE and EPS."""
    from services.backlog.valuation import fetch_valuation
    t = ticker.strip().upper()
    if not t or len(t) > 20:
        return jsonify({"error": "invalid ticker"}), 400
    return jsonify(fetch_valuation(t))


@app.route("/api/analyze", methods=["POST"])
def analyze() -> Response:
    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400

    # 6-3: Submit to AsyncRunner and return immediately.
    # Frontend polls GET /api/analyze/status/<job_id> until status == "done".
    job_id = async_runner.submit(investment_run_analysis, query)
    return jsonify({"job_id": job_id, "status": "running"})


@app.route("/api/analyze/status/<job_id>")
def analyze_status(job_id: str) -> Response:
    """6-3: Poll analysis job status.

    Returns:
        running:  {"status": "running", "message": "started"}
        done:     {"status": "done", "result": "<analysis text>"}
        error:    {"status": "error", "message": "<reason>"}
        not_found:{"status": "not_found"}
    """
    return jsonify(async_runner.get_status(job_id))


# ── Screener endpoints ────────────────────────────────────────────────────────

from services.screener import runner as _screener_runner  # noqa: E402

_SCREENER_VALID_MARKETS = {"SP500", "NASDAQ100", "DAX40", "TW50"}


@app.route("/api/screener/start", methods=["POST"])
def screener_start() -> Response:
    """Start (or resume) a screener job for a given market.

    Request JSON: {"market": "SP500" | "NASDAQ100" | "DAX40" | "TW50"}
    Response:     {"job_id": "<uuid>", "status": "running" | "done"}
    """
    data = request.get_json(silent=True) or {}
    market = (data.get("market") or "").strip().upper()
    force  = bool(data.get("force", False))
    if market not in _SCREENER_VALID_MARKETS:
        return jsonify({"error": f"Invalid market: {market!r}. Choose from {sorted(_SCREENER_VALID_MARKETS)}"}), 400
    try:
        job_id = _screener_runner.start_screener(market, force=force)
        state = _screener_runner.get_screener_status(job_id)
        return jsonify({"job_id": job_id, "status": state.get("status", "running")})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/screener/pause/<job_id>", methods=["POST"])
def screener_pause(job_id: str) -> Response:
    """Pause a running screener job."""
    ok = _screener_runner.pause_screener(job_id)
    if not ok:
        return jsonify({"error": "Job not found or not in running state"}), 404
    return jsonify({"ok": True})


@app.route("/api/screener/resume/<job_id>", methods=["POST"])
def screener_resume(job_id: str) -> Response:
    """Resume a paused screener job."""
    ok = _screener_runner.resume_screener(job_id)
    if not ok:
        return jsonify({"error": "Job not found or not in paused state"}), 404
    return jsonify({"ok": True})


@app.route("/api/screener/cancel/<job_id>", methods=["POST"])
def screener_cancel(job_id: str) -> Response:
    """Cancel a running or paused screener job."""
    ok = _screener_runner.cancel_screener(job_id)
    return jsonify({"ok": ok})


@app.route("/api/screener/status/<job_id>")
def screener_status(job_id: str) -> Response:
    """Get the current status of a screener job."""
    state = _screener_runner.get_screener_status(job_id)
    return jsonify(state)




@app.route("/api/policy", methods=["GET"])
def policy() -> Response:
    jurisdiction = request.args.get("jurisdiction", "ALL")
    keyword = request.args.get("keyword", "")
    from_date = request.args.get("from_date", "2024-01-01")
    to_date = request.args.get("to_date", "2026-12-31")
    limit = int(request.args.get("limit", "10"))

    if not keyword:
        return jsonify({"error": "keyword is required"}), 400

    try:
        events = _policy_agent.query_updates(jurisdiction, keyword, from_date, to_date, limit)
        return jsonify({
            "count": len(events),
            "events": [
                {
                    "id": e.id,
                    "source": e.source,
                    "title": e.title,
                    "published_at": e.published_at.isoformat(),
                    "jurisdictions": e.jurisdictions,
                    "url": e.url,
                    "summary": e.summary,
                }
                for e in events
            ],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Policy Outlook & Sentiment Feed (UI sidebar) ─────────────────────────────

from UI.app_server import (  # noqa: E402
    _build_policy_outlook,
    _build_sentiment_feed,
    _load_events,
    _ai_rewrite_items,
    _now_utc,
    _sample_events,
    _wants_ai,
)


@app.route("/api/policy-outlook")
def policy_outlook() -> Response:
    keyword = (request.args.get("keyword") or "ai regulation")
    days = int(request.args.get("days") or 180)
    limit = int(request.args.get("limit") or 20)
    ai_enabled = _wants_ai({"ai": [request.args.get("ai", "off")]})
    try:
        events = _load_events(keyword=keyword, days=days, limit=limit)
    except Exception as exc:
        events = _sample_events()
        deterministic = _build_policy_outlook(events)
        rewritten_items, ai_meta = _ai_rewrite_items("policy", deterministic["items"], ai_enabled)
        return jsonify({"items": rewritten_items, "updated_at": _now_utc().isoformat(), "warning": str(exc), "ai": ai_meta})
    payload = _build_policy_outlook(events)
    payload["items"], payload["ai"] = _ai_rewrite_items("policy", payload["items"], ai_enabled)
    return jsonify(payload)


@app.route("/api/sentiment-feed")
def sentiment_feed() -> Response:
    keyword = (request.args.get("keyword") or "ai regulation")
    days = int(request.args.get("days") or 180)
    limit = int(request.args.get("limit") or 20)
    ai_enabled = _wants_ai({"ai": [request.args.get("ai", "off")]})
    try:
        events = _load_events(keyword=keyword, days=days, limit=limit)
    except Exception as exc:
        events = _sample_events()
        deterministic = _build_sentiment_feed(events)
        rewritten_items, ai_meta = _ai_rewrite_items("sentiment", deterministic["items"], ai_enabled)
        return jsonify({"items": rewritten_items, "updated_at": _now_utc().isoformat(), "warning": str(exc), "ai": ai_meta})
    payload = _build_sentiment_feed(events)
    payload["items"], payload["ai"] = _ai_rewrite_items("sentiment", payload["items"], ai_enabled)
    return jsonify(payload)




# ── Taiwan Market Endpoints ──────────────────────────────────────────────────

@app.route("/api/tw/dashboard/summary")
def tw_dashboard_summary() -> Response:
    """Taiwan stock dashboard summary."""
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    result = tw_build_dashboard_summary(ticker)
    status_code = 200 if "error" not in result.get("summary", {}) else 502
    return jsonify(result), status_code


@app.route("/api/tw/market/overview")
def tw_market_overview() -> Response:
    """Taiwan market overview (TAIEX, OTC)."""
    result = tw_build_market_index()
    status_code = 200 if "error" not in result else 502
    return jsonify(result), status_code


@app.route("/api/tw/dashboard/management")
def tw_dashboard_management() -> Response:
    """Taiwan stock management quality metrics."""
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    result = tw_build_management_snapshot(ticker)
    status_code = 200 if "error" not in result else 502
    return jsonify(result), status_code


@app.route("/api/tw/documents/recent-announcements")
def tw_recent_announcements() -> Response:
    """Taiwan stock recent announcements/news."""
    ticker = (request.args.get("ticker") or "").strip()
    limit = int(request.args.get("limit", "10"))

    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    result = build_recent_announcements(ticker, limit=limit)
    status_code = 200 if "error" not in result else 502
    return jsonify(result), status_code


@app.route("/api/tw/documents/financial-statements")
def tw_financial_statements() -> Response:
    """Taiwan stock financial statements (年報/季報)."""
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    result = build_financial_statements(ticker)
    status_code = 200 if "error" not in result else 502
    return jsonify(result), status_code


@app.route("/api/tw/documents/annual-report")
def tw_annual_report() -> Response:
    """Taiwan stock annual report summary (年報摘要)."""
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    result = build_annual_report_summary(ticker)
    status_code = 200 if "error" not in result else 502
    return jsonify(result), status_code


# ── Financial Health ─────────────────────────────────────────────────────────

# In-memory cache: {ticker: {data, scores, cached_at}}
_fh_data_cache = {}
_FH_CACHE_TTL = 1800  # 30 minutes

import time as _time


def _fh_cache_get(ticker: str):
    entry = _fh_data_cache.get(ticker.upper())
    if entry and (_time.time() - entry["cached_at"]) < _FH_CACHE_TTL:
        return entry
    return None


_TICKER_RE = re.compile(r'^[A-Z0-9.]{1,10}$')


def _sanitize_nan(obj):
    """Recursively replace float NaN/Inf with None for valid JSON serialization."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan(v) for v in obj]
    return obj


_fx_cache: dict = {}


@app.route("/api/exchange-rate")
def exchange_rate() -> Response:
    """Return USD→EUR rate via yfinance. Cached 10 min."""
    import yfinance as yf
    import time as _t
    cached = _fx_cache.get('EURUSD')
    if cached and (_t.time() - cached['at']) < 600:
        return jsonify(cached['payload'])
    try:
        info = yf.Ticker('EURUSD=X').fast_info
        eurusd = float(info.get('lastPrice') or info.get('last_price') or 1.0)
        # EURUSD=X = how many USD per 1 EUR; invert to get USD→EUR multiplier
        rate = 1.0 / eurusd if eurusd else 1.0
    except Exception:
        rate = (_fx_cache.get('EURUSD') or {}).get('payload', {}).get('rate', 1.0)
    payload = {'base': 'USD', 'quote': 'EUR', 'rate': round(rate, 6)}
    _fx_cache['EURUSD'] = {'payload': payload, 'at': _t.time()}
    return jsonify(payload)


@app.route("/api/financial_health/transcript/<ticker>")
def fh_transcript(ticker: str) -> Response:
    """Fetch latest earnings transcript for a ticker (FMP → HF cache → EDGAR)."""
    from tools.earnings_transcript import EarningsTranscriptTool
    t = ticker.strip().upper()
    if not _TICKER_RE.match(t):
        return jsonify({"error": "invalid_ticker"}), 400
    return jsonify(EarningsTranscriptTool().execute({"ticker": t}))


@app.route("/api/financial_health/data")
def financial_health_data() -> Response:
    """Fetch + score financial health data for a ticker."""
    ticker = (request.args.get("ticker") or "").strip().upper()
    lang   = (request.args.get("lang") or "en").strip().lower()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    cached = _fh_cache_get(ticker)
    if cached:
        return jsonify({**cached["payload"], "cached": True}), 200

    raw = fetch_financial_health(ticker)
    if raw.get("error"):
        return jsonify(raw), 502

    scoring = score_financial_health(raw["fundamentals"])
    year_scores = score_financial_health_multiyear(raw["fundamentals"], raw["years"])

    payload = {
        "ticker":       raw["ticker"],
        "years":        raw["years"],
        "fundamentals": raw["fundamentals"],
        "info":         raw["info"],
        "scores":       scoring["indicator_scores"],
        "group_scores": scoring["group_scores"],
        "weighted_100": scoring["weighted_100"],
        "year_scores":  year_scores[:5],
        "data_source":  raw.get("data_source", "yfinance"),
        "cached":       False,
    }
    clean = _sanitize_nan(payload)
    _fh_data_cache[ticker] = {"payload": clean, "raw": raw, "scoring": scoring, "cached_at": _time.time()}
    return jsonify(clean), 200


@app.route("/api/financial_health/summary", methods=["POST"])
def financial_health_summary() -> Response:
    """LLM financial health summary for a ticker."""
    body   = request.get_json(silent=True) or {}
    ticker = (body.get("ticker") or "").strip().upper()
    lang   = (body.get("lang") or "en").strip().lower()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    cached = _fh_cache_get(ticker)
    if cached:
        raw     = cached["raw"]
        scoring = cached["scoring"]
    else:
        raw = fetch_financial_health(ticker)
        if raw.get("error"):
            return jsonify(raw), 502
        scoring = score_financial_health(raw["fundamentals"])
        _fh_data_cache[ticker] = {"payload": {}, "raw": raw, "scoring": scoring, "cached_at": _time.time()}

    result = fh_health_summary(ticker, raw["fundamentals"], raw["years"], scoring, lang)
    return jsonify(result), 200


@app.route("/api/financial_health/drilldown", methods=["POST"])
def financial_health_drilldown() -> Response:
    """LLM contribution drill-down analysis for a ticker."""
    body   = request.get_json(silent=True) or {}
    ticker = (body.get("ticker") or "").strip().upper()
    lang   = (body.get("lang") or "en").strip().lower()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    cached = _fh_cache_get(ticker)
    if cached:
        raw = cached["raw"]
    else:
        raw = fetch_financial_health(ticker)
        if raw.get("error"):
            return jsonify(raw), 502
        scoring = score_financial_health(raw["fundamentals"])
        _fh_data_cache[ticker] = {"payload": {}, "raw": raw, "scoring": scoring, "cached_at": _time.time()}

    # Try to get latest transcript excerpt (graceful fallback)
    transcript_excerpt = None
    try:
        from data_sources.transcripts.hf_cache import get_cached_transcript
        tc = get_cached_transcript(ticker)
        if "error" not in tc:
            transcript_excerpt = tc.get("content_excerpt") or tc.get("content")
    except Exception:
        pass

    result = fh_drilldown_analysis(ticker, raw["fundamentals"], raw["years"], transcript_excerpt, lang)
    return jsonify(result), 200


# ── Competitor Comparison routes ──────────────────────────────────────────────

_peers_cache: dict = {}
_PEERS_CACHE_TTL = 300  # 5 minutes


@app.route("/api/fh/peers/<path:ticker>")
def fh_peers(ticker: str) -> Response:
    """Return up to 5 peer tickers for a given stock with 5-minute in-memory cache."""
    from services.financial_health.competitor import get_peers
    t = ticker.strip().upper()
    if not t:
        return jsonify({"error": "ticker required"}), 400

    entry = _peers_cache.get(t)
    if entry and (_time.time() - entry["cached_at"]) < _PEERS_CACHE_TTL:
        return jsonify(entry["data"]), 200

    data = get_peers(t)
    _peers_cache[t] = {"data": data, "cached_at": _time.time()}
    return jsonify(data), 200


@app.route("/api/fh/competitor_compare", methods=["POST"])
def fh_competitor_compare() -> Response:
    """Compare main company against up to 4 competitors across multiple dimensions."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from services.financial_health.competitor import (
        get_company_profile,
        get_price_history,
        get_analyst_ratings,
        get_competitor_fh_scores,
        get_linkedin_jobs,
        get_llm_business_diff,
    )

    body = request.get_json(silent=True) or {}
    ticker = (body.get("ticker") or "").strip().upper()
    competitors_raw = body.get("competitors") or []

    if not ticker:
        return jsonify({"error": "ticker is required"}), 400
    if not isinstance(competitors_raw, list) or not competitors_raw:
        return jsonify({"error": "competitors must be a non-empty list"}), 400

    # Validate and clean competitor tickers
    competitors = []
    for c in competitors_raw:
        c = str(c).strip().upper()
        if c and c != ticker and c not in competitors and not c.isdigit():
            competitors.append(c)
    competitors = competitors[:4]

    if not competitors:
        return jsonify({"error": "no valid competitor tickers provided"}), 400

    all_tickers = [ticker] + competitors

    # Parallel fetch: profile, price_history, analyst_ratings, fh_scores
    profiles_result = {}
    price_result = {}
    analyst_result = {}
    fh_result = {}
    linkedin_result = {}

    def _fetch_profiles():
        return get_company_profile(all_tickers)

    def _fetch_prices():
        return get_price_history(all_tickers, period="1y")

    def _fetch_analysts():
        return get_analyst_ratings(all_tickers)

    def _fetch_fh():
        return get_competitor_fh_scores(all_tickers, _fh_data_cache)

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_profiles  = ex.submit(_fetch_profiles)
        f_prices    = ex.submit(_fetch_prices)
        f_analysts  = ex.submit(_fetch_analysts)
        f_fh        = ex.submit(_fetch_fh)

        try:
            for f in as_completed([f_profiles, f_prices, f_analysts, f_fh], timeout=60):
                pass  # wait for all; individual result() calls below handle per-future errors
        except TimeoutError:
            pass  # some futures didn't finish in 60s; result(timeout=1) below will surface errors

    try:
        profiles_result = f_profiles.result(timeout=1)
    except Exception as e:
        logger.warning("Profiles fetch failed: %s", e)

    try:
        price_result = f_prices.result(timeout=1)
    except Exception as e:
        logger.warning("Price history fetch failed: %s", e)

    try:
        analyst_result = f_analysts.result(timeout=1)
    except Exception as e:
        logger.warning("Analyst ratings fetch failed: %s", e)

    try:
        fh_result = f_fh.result(timeout=1)
    except Exception as e:
        logger.warning("FH scores fetch failed: %s", e)

    # LinkedIn (best-effort, serial — fragile scraping)
    company_names = {t: (profiles_result.get(t) or {}).get("companyName") or t for t in all_tickers}
    try:
        linkedin_result = get_linkedin_jobs(all_tickers, company_names)
    except Exception as e:
        logger.warning("LinkedIn jobs failed: %s", e)
        linkedin_result = {t: {"count": None, "source": "unavailable"} for t in all_tickers}

    # LLM business diff (depends on profiles)
    business_diff = {"summary": None, "key_diffs": [], "ai_generated": True}
    try:
        business_diff = get_llm_business_diff(ticker, competitors, profiles_result)
    except Exception as e:
        logger.warning("LLM business diff failed: %s", e)

    # Assemble response
    def _company_data(t: str) -> dict:
        return {
            "ticker":    t,
            "profile":   profiles_result.get(t) or {},
            "fh_score":  fh_result.get(t) or {"total_score": None, "group_scores": None, "indicator_scores": None},
            "analyst":   analyst_result.get(t) or {},
            "linkedin":  linkedin_result.get(t) or {"count": None, "source": "unavailable"},
        }

    response_data = {
        "main": _company_data(ticker),
        "competitors": [
            {**_company_data(c), "price_history": price_result.get(c) or []}
            for c in competitors
        ],
        "price_history_main": price_result.get(ticker) or [],
        "business_diff": business_diff,
    }

    return jsonify(response_data), 200


# ── Supply Chain routes ────────────────────────────────────────────────────────

_SC_DISCOVER_CACHE: dict = {}
_SC_DISCOVER_TTL = 21600   # 6 hours — supply chain structure rarely changes
_SC_ANALYZE_CACHE: dict = {}
_SC_ANALYZE_TTL  = 1800    # 30 minutes


@app.route("/api/supply_chain/discover", methods=["POST"])
def supply_chain_discover() -> Response:
    """LLM-powered supply chain discovery for a ticker."""
    body   = request.get_json(silent=True) or {}
    ticker = (body.get("ticker") or "").strip().upper()
    lang   = (body.get("lang") or "en").strip().lower()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    cache_key = f"{ticker}:{lang}"
    entry = _SC_DISCOVER_CACHE.get(cache_key)
    if entry and (_time.time() - entry["cached_at"]) < _SC_DISCOVER_TTL:
        return jsonify({**entry["data"], "cached": True}), 200

    data = sc_discover(ticker, lang)
    if data.get("error") and not data.get("nodes"):
        return jsonify(data), 502

    _SC_DISCOVER_CACHE[cache_key] = {"data": data, "cached_at": _time.time()}
    return jsonify({**data, "cached": False}), 200


@app.route("/api/supply_chain/analyze_node", methods=["POST"])
def supply_chain_analyze_node() -> Response:
    """LLM read-through analysis for a specific supply chain node."""
    body          = request.get_json(silent=True) or {}
    center_ticker = (body.get("center_ticker") or "").strip().upper()
    center_name   = (body.get("center_name") or center_ticker).strip()
    node_ticker   = (body.get("node_ticker") or "").strip().upper()
    node_name     = (body.get("node_name") or node_ticker).strip()
    relation      = (body.get("relation") or "peer").strip().lower()
    lang          = (body.get("lang") or "en").strip().lower()
    if not center_ticker or not node_ticker:
        return jsonify({"error": "center_ticker and node_ticker are required"}), 400

    cache_key = f"{center_ticker}:{node_ticker}:{lang}"
    entry = _SC_ANALYZE_CACHE.get(cache_key)
    if entry and (_time.time() - entry["cached_at"]) < _SC_ANALYZE_TTL:
        return jsonify({**entry["data"], "cached": True}), 200

    # Optional: pull transcript excerpt for the center company
    transcript_excerpt = None
    try:
        from data_sources.transcripts.hf_cache import get_cached_transcript
        tc = get_cached_transcript(center_ticker)
        if "error" not in tc:
            transcript_excerpt = tc.get("content_excerpt") or tc.get("content")
            if transcript_excerpt:
                transcript_excerpt = transcript_excerpt[:4000]
    except Exception:
        pass

    # Optional: pull financial summary from FH cache
    financial_summary = None
    fh_entry = _fh_data_cache.get(center_ticker)
    if fh_entry and fh_entry.get("raw"):
        raw_fh = fh_entry["raw"]
        funda  = raw_fh.get("fundamentals", {})
        years  = raw_fh.get("years", [])
        score  = fh_entry.get("scoring", {}).get("weighted_100")
        lines  = [f"Health Score: {score}/100"] if score else []
        for metric in ("revenueGrowth", "grossProfitMargin", "returnOnEquity", "freeCashFlowGrowth", "DebtToEquity"):
            vals = funda.get(metric)
            if vals:
                try:
                    v = float(vals[0])
                    yr = years[0] if years else ""
                    lines.append(f"  {metric} ({yr}): {v*100:.1f}%" if abs(v) < 50 else f"  {metric} ({yr}): {v:.2f}")
                except Exception:
                    pass
        financial_summary = "\n".join(lines) if lines else None

    result = sc_analyze_node(
        center_ticker, center_name, node_ticker, node_name, relation,
        transcript_excerpt, financial_summary, lang
    )
    if not result.get("error"):
        _SC_ANALYZE_CACHE[cache_key] = {"data": result, "cached_at": _time.time()}
    return jsonify(result), 200


@app.route("/api/llm/status")
def llm_status() -> Response:
    """Return current LLM provider status — useful for health monitoring and debugging."""
    from agent.llm_client import get_provider_status
    return jsonify(get_provider_status()), 200


# ── Chip Analysis ──────────────────────────────────────────────────────────────

@app.route("/api/chips/summary/<ticker>")
def chips_summary(ticker: str) -> Response:
    """Level 1 fast data: volume (RVOL/VWAP) + short interest."""
    from services.chips.volume import fetch_volume_data
    from services.chips.short_interest import fetch_short_interest

    vol = fetch_volume_data(ticker)
    short = fetch_short_interest(ticker)
    return jsonify({"ticker": ticker.upper(), "volume": vol, "short": short}), 200


@app.route("/api/chips/options/<ticker>")
def chips_options(ticker: str) -> Response:
    """Level 2 options flow: PCR, Max Pain, OI distribution."""
    from services.chips.options_flow import fetch_options_flow

    return jsonify(fetch_options_flow(ticker)), 200


@app.route("/api/chips/institutional/<ticker>")
def chips_institutional(ticker: str) -> Response:
    """Level 2-3 institutional data: 13F holders, Form 4 insider trades, ETF holders."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from services.chips.institutional import fetch_institutional
    from services.chips.insider import fetch_insider
    from services.chips.etf_flow import fetch_etf_holders

    results = {}
    tasks = {
        "institutional": (fetch_institutional, ticker),
        "insider": (fetch_insider, ticker),
        "etf": (fetch_etf_holders, ticker),
    }

    with ThreadPoolExecutor(max_workers=3) as ex:
        future_map = {ex.submit(fn, t): key for key, (fn, t) in tasks.items()}
        for future in as_completed(future_map, timeout=15):
            key = future_map[future]
            try:
                results[key] = future.result()
            except Exception as e:
                results[key] = {"error": str(e)}

    return jsonify({"ticker": ticker.upper(), **results}), 200


@app.route("/api/company/news")
def company_news() -> Response:
    """Fetch and categorise recent company news via yfinance."""
    ticker = request.args.get("ticker", "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker required", "items": []})
    try:
        import yfinance as yf
        raw = yf.Ticker(ticker).news or []
        _CATS: dict[str, list[str]] = {
            "legal":     ["lawsuit", "sue", "legal", "court", "litigation", "settlement",
                          "verdict", "penalty", "fine", "regulatory", "class action",
                          "investigation", "antitrust", "ftc charges", "sec charges"],
            "product":   ["launch", "release", "unveil", "new product", "introduces",
                          "debut", "ships", "rolls out", "announces new"],
            "tech":      ["ai ", "artificial intelligence", "chip", "software", "hardware",
                          "patent", "algorithm", "innovation", "breakthrough", "model"],
            "financial": ["earnings", "revenue", "profit", "loss", "quarterly", "eps",
                          "dividend", "buyback", "guidance", "forecast", "outlook"],
            "deal":      ["acquire", "merger", "acquisition", "deal", "partnership",
                          "joint venture", "invest", "stake"],
        }

        def _cat(title: str) -> str:
            tl = title.lower()
            for k, kws in _CATS.items():
                if any(w in tl for w in kws):
                    return k
            return "general"

        items = [
            {
                "title": n.get("title", ""),
                "publisher": n.get("publisher", ""),
                "link": n.get("link", ""),
                "published_at": n.get("providerPublishTime", 0),
                "category": _cat(n.get("title", "")),
            }
            for n in raw[:20]
        ]
        return jsonify({"ticker": ticker, "items": items,
                        "fetched_at": datetime.now().isoformat()[:19]})
    except Exception as exc:
        return jsonify({"error": str(exc), "items": [], "ticker": ticker})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  OpenOctopus running -> http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
