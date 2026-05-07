"""
OpenOctopus — Flask web server.

Serves the dashboard UI and exposes API endpoints backed by the
investment analysis agent (Azure / OpenAI-compatible).

Usage:
    python app.py          # starts on http://localhost:5000
"""
import json
import os
import sys
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
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/dashboard/tw")
def dashboard_tw() -> Response:
    html_path = str(UI_DIR / "dashboard-tw.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


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


# ── Investment Analysis ─────────────────────────────────────────────────────

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


# ── Policy Query ─────────────────────────────────────────────────────────────

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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  OpenOctopus running -> http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
