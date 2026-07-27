from __future__ import annotations

import json
import mimetypes
import re
import sys
import time as _time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
UI_DIR = ROOT_DIR / "UI"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.policy_monitoring import PolicyMonitoringAgent  # noqa: E402
from agent.llm_client import get_llm_client  # noqa: E402
from config import settings  # noqa: E402

_CACHE: dict[str, Any] = {"ts": None, "events": []}
_CACHE_TTL_SECONDS = 300

# In-memory screener job store (cleared on restart — acceptable for demo)
_SCREENER_JOBS: dict[str, dict[str, Any]] = {}

# Exchange-rate cache: {key: {"rate": float, "at": float}}
_fx_cache: dict[str, dict[str, Any]] = {}
_FX_PAIRS = [
    ("EURUSD=X",  True,  "EURUSD"),   # raw = USD per EUR → invert to get USD→EUR
    ("USDTWD=X",  False, "USDTWD"),   # raw = TWD per USD
    ("USDCNY=X",  False, "USDCNY"),   # raw = CNY per USD
]


def _wants_ai(query: dict[str, list[str]]) -> bool:
    raw = (query.get("ai", ["off"]) or ["off"])[0].strip().lower()
    return raw in {"on", "1", "true", "yes"}


def _get_exchange_rates() -> dict[str, Any]:
    """Fetch USD/EUR, USD/TWD, USD/CNY from yfinance with 10-min in-memory cache."""
    try:
        import yfinance as yf
    except ImportError:
        return {"pairs": {"EURUSD": 1.08, "USDTWD": 32.5, "USDCNY": 7.25},
                "base": "USD", "rate": 1.08}

    now = _time.time()
    pairs: dict[str, float] = {}
    for yf_sym, invert, key in _FX_PAIRS:
        cached = _fx_cache.get(key)
        if cached and (now - cached["at"]) < 600:
            pairs[key] = cached["rate"]
            continue
        try:
            info = yf.Ticker(yf_sym).fast_info
            raw = float(getattr(info, "last_price", None) or 0)
            rate = (1.0 / raw if raw else 1.0) if invert else (raw or 1.0)
        except Exception:
            rate = (_fx_cache.get(key) or {}).get("rate", 1.0)
        _fx_cache[key] = {"rate": rate, "at": now}
        pairs[key] = rate

    return {
        "pairs": {k: round(v, 6) for k, v in pairs.items()},
        "base": "USD",
        "rate": round(pairs.get("EURUSD", 1.0), 6),
    }


def _extract_text_payload(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return ""


def _parse_first_json_array(text: str) -> list[dict[str, Any]] | None:
    if not text:
        return None
    fenced = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidates = fenced + [text]
    for candidate in candidates:
        start = candidate.find("[")
        end = candidate.rfind("]")
        if start == -1 or end == -1 or end <= start:
            continue
        snippet = candidate[start : end + 1]
        try:
            parsed = json.loads(snippet)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            clean = [x for x in parsed if isinstance(x, dict)]
            return clean
    return None


def _ai_rewrite_items(kind: str, items: list[dict[str, Any]], enabled: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not enabled:
        return items, {"mode": "deterministic", "ai_used": False}

    try:
        client = get_llm_client()
    except Exception:
        return items, {"mode": "ai", "ai_used": False, "warning": "LLM client is not configured."}

    if kind == "policy":
        instruction = (
            "Rewrite each policy card for an institutional audience. "
            "Return ONLY a JSON array with the same length and keys: "
            "title (string), windowPct (integer 0-100), expires (string), severity ('high'|'medium')."
        )
    else:
        instruction = (
            "Rewrite each sentiment item with sharper risk/opportunity phrasing. "
            "Return ONLY a JSON array with the same length and keys: "
            "label (string), tone ('positive'|'negative'|'alert'), time (string), tag (string), headline (string)."
        )

    items_to_rewrite = items[:8]
    estimated_max_tokens = min(120 * len(items_to_rewrite) + 200, 2000)
    try:
        response = client.chat.completions.create(
            model=settings.MODEL,
            messages=[
                {"role": "system", "content": "You are a financial policy and market narrative editor."},
                {
                    "role": "user",
                    "content": (
                        f"{instruction}\n"
                        "Do not add commentary. Output raw JSON array only.\n"
                        f"Input items JSON:\n{json.dumps(items_to_rewrite, ensure_ascii=True)}"
                    ),
                },
            ],
            max_tokens=estimated_max_tokens,
            timeout=min(max(settings.API_TIMEOUT, 8), 45),
        )
        usage = getattr(response, "usage", None)
        content = _extract_text_payload(response.choices[0].message.content if response.choices else "")
        rewritten = _parse_first_json_array(content)
        if rewritten and len(rewritten) >= max(1, len(items_to_rewrite) // 2):
            merged = rewritten + items_to_rewrite[len(rewritten):]
            merged += items[len(items_to_rewrite):]
            return merged[:len(items)], {
                "mode": "ai",
                "ai_used": True,
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
                "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
            }
        return items, {
            "mode": "ai",
            "ai_used": False,
            "warning": f"AI response was not valid JSON array (got {len(rewritten) if rewritten else 0}/{len(items_to_rewrite)} items); kept deterministic content.",
        }
    except Exception as exc:
        return items, {
            "mode": "ai",
            "ai_used": False,
            "warning": f"AI rewrite failed: {exc}",
        }


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _quarter_label(dt: datetime) -> str:
    return f"{dt.year}-Q{((dt.month - 1) // 3) + 1}"


def _window_pct(effective_to: str | None) -> int:
    if not effective_to:
        return 50
    try:
        expires = datetime.fromisoformat(effective_to.replace("Z", "+00:00"))
        remaining_days = (expires - _now_utc()).days
        return max(0, min(100, int((remaining_days / 365) * 100)))
    except Exception:
        return 50


def _time_label(iso_dt: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_dt.replace("Z", "+00:00"))
        return dt.strftime("%H:%M UTC")
    except Exception:
        return "Unknown"


def _tag_from_event(ev: dict[str, Any]) -> str:
    topics = ev.get("topics") or []
    topics_text = " ".join(topics).lower()
    if "ai" in topics_text or "digital" in topics_text or "market_structure" in topics_text:
        return "tech"
    if ev.get("source") in ("SEC", "FEDERAL_REGISTER"):
        return "policy"
    return "macro"


def _load_events(keyword: str, days: int, limit: int) -> list[dict[str, Any]]:
    now = _now_utc()
    ts = _CACHE.get("ts")
    if ts and (now - ts).total_seconds() < _CACHE_TTL_SECONDS and _CACHE.get("events"):
        return _CACHE["events"]

    from_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    agent = PolicyMonitoringAgent()
    events = agent.query_updates(
        jurisdiction="ALL",
        keyword=keyword,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )
    payload = [e.to_dict() for e in events]
    _CACHE["ts"] = now
    _CACHE["events"] = payload
    return payload


def _sample_events() -> list[dict[str, Any]]:
    now = _now_utc()
    return [
        {
            "id": "sample-1",
            "source": "FEDERAL_REGISTER",
            "title": "Trade Tariff Exemption 4-A",
            "summary": "Temporary exemption window extended for critical semiconductor imports.",
            "published_at": now.isoformat(),
            "effective_to": (now + timedelta(days=280)).isoformat(),
            "topics": ["market_structure"],
        },
        {
            "id": "sample-2",
            "source": "SEC",
            "title": "Semiconductor Subsidy Phase 2",
            "summary": "Second phase implementation notice introduces narrower eligibility criteria.",
            "published_at": (now - timedelta(days=1)).isoformat(),
            "effective_to": (now + timedelta(days=120)).isoformat(),
            "topics": ["ai_regulation"],
        },
        {
            "id": "sample-3",
            "source": "EUR_LEX",
            "title": "EU AI Act Compliance Window",
            "summary": "Compliance obligations enter final pre-enforcement phase for high-risk models.",
            "published_at": (now - timedelta(days=2)).isoformat(),
            "effective_to": (now + timedelta(days=60)).isoformat(),
            "topics": ["ai_regulation", "data_privacy"],
        },
    ]


def _build_policy_outlook(events: list[dict[str, Any]]) -> dict[str, Any]:
    cards = []
    for ev in events[:3]:
        pct = _window_pct(ev.get("effective_to"))
        severity = "high" if pct <= 25 else "medium"
        expires = "Ongoing"
        if ev.get("effective_to"):
            try:
                dt = datetime.fromisoformat(ev["effective_to"].replace("Z", "+00:00"))
                expires = _quarter_label(dt)
            except Exception:
                expires = "Ongoing"
        cards.append(
            {
                "title": ev.get("title", "Untitled Policy Event"),
                "windowPct": pct,
                "expires": expires,
                "severity": severity,
            }
        )

    return {"items": cards, "updated_at": _now_utc().isoformat()}


def _build_sentiment_feed(events: list[dict[str, Any]]) -> dict[str, Any]:
    from agent.policy_monitoring.rules import classify_impact
    from agent.policy_monitoring.schemas import PolicyEvent

    feed = []
    for ev in events[:12]:
        try:
            model = PolicyEvent(**ev)
            cls = classify_impact(model)
            if cls.impact == "opportunity":
                label, tone = "Positive", "positive"
            elif cls.impact == "constraint":
                label, tone = "Negative", "negative"
            else:
                label, tone = "Alert", "alert"
        except Exception:
            label, tone = "Alert", "alert"

        feed.append(
            {
                "label": label,
                "tone": tone,
                "time": _time_label(ev.get("published_at", "")),
                "tag": _tag_from_event(ev),
                "headline": ev.get("summary") or ev.get("title") or "No summary available.",
            }
        )

    return {"items": feed, "updated_at": _now_utc().isoformat()}


class UiApiHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    # ── Response helpers ────────────────────────────────────────────────────────

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html_file(self, filename: str) -> None:
        """Serve an HTML file from UI_DIR."""
        full_path = UI_DIR / filename
        if not full_path.is_file():
            self._send_json({"error": f"{filename} not found"}, 404)
            return
        content = full_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(content)

    # ── CORS pre-flight ─────────────────────────────────────────────────────────

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── GET ─────────────────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # ── Static files: /static/<file> → serve from UI_DIR/<file> ──────────
        if path.startswith("/static/"):
            rel = path[len("/static/"):]          # strip /static/ prefix
            full = UI_DIR / rel
            if full.is_file():
                content = full.read_bytes()
                mime, _ = mimetypes.guess_type(str(full))
                self.send_response(200)
                self.send_header("Content-Type", mime or "application/octet-stream")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)
            else:
                self._send_json({"error": f"Static file not found: {rel}"}, 404)
            return

        # ── Dashboard HTML routes ─────────────────────────────────────────────
        if path in ("/", "/dashboard/us"):
            self._send_html_file("index.html")
            return

        if path == "/dashboard/tw":
            self._send_html_file("dashboard-tw.html")
            return

        if path == "/test":
            self._send_html_file("test-dashboard.html")
            return

        # ── Health ────────────────────────────────────────────────────────────
        if path == "/api/health":
            self._send_json({"status": "ok", "server": "app_server"})
            return

        # ── Exchange rate ─────────────────────────────────────────────────────
        if path == "/api/exchange-rate":
            self._send_json(_get_exchange_rates())
            return

        # ── Screener status ───────────────────────────────────────────────────
        if path.startswith("/api/screener/status/"):
            job_id = path.split("/")[-1]
            state = _SCREENER_JOBS.get(
                job_id,
                {"status": "error", "error": "Job not found", "passing": [], "total": 0},
            )
            self._send_json(state)
            return

        # ── Taiwan chips (institutional) ──────────────────────────────────────
        if path == "/api/tw/chips/institutional":
            query = parse_qs(parsed.query)
            ticker = (query.get("ticker", ["2330"]) or ["2330"])[0]
            try:
                from data_sources.tw.institutional import get_institutional_data
                data = get_institutional_data(ticker)
                self._send_json({"ticker": ticker, "data": data})
            except Exception as exc:
                self._send_json({"ticker": ticker, "data": [], "warning": str(exc)})
            return

        # ── Taiwan chips (margin) ─────────────────────────────────────────────
        if path == "/api/tw/chips/margin":
            query = parse_qs(parsed.query)
            ticker = (query.get("ticker", ["2330"]) or ["2330"])[0]
            try:
                from data_sources.tw.margin import get_margin_data
                data = get_margin_data(ticker)
                self._send_json({"ticker": ticker, "data": data})
            except Exception as exc:
                self._send_json({"ticker": ticker, "data": [], "warning": str(exc)})
            return

        # ── Financial health data ─────────────────────────────────────────────
        if path == "/api/financial_health/data":
            query = parse_qs(parsed.query)
            ticker = (query.get("ticker", ["AAPL"]) or ["AAPL"])[0].upper()
            try:
                from services.financial_health.fetcher import fetch_financial_health
                data = fetch_financial_health(ticker)
                self._send_json(data)
            except Exception as exc:
                self._send_json({"ticker": ticker, "scores": {}, "warning": str(exc)})
            return

        # ── Policy outlook ────────────────────────────────────────────────────
        if path == "/api/policy-outlook":
            query = parse_qs(parsed.query)
            keyword = (query.get("keyword", ["ai regulation"]) or ["ai regulation"])[0]
            days = int((query.get("days", ["180"]) or ["180"])[0])
            limit = int((query.get("limit", ["20"]) or ["20"])[0])
            ai_enabled = _wants_ai(query)
            try:
                events = _load_events(keyword=keyword, days=days, limit=limit)
            except Exception as exc:
                events = _sample_events()
                deterministic = _build_policy_outlook(events)
                rewritten_items, ai_meta = _ai_rewrite_items("policy", deterministic["items"], ai_enabled)
                self._send_json({"items": rewritten_items, "updated_at": _now_utc().isoformat(), "warning": f"Fallback sample data used: {exc}", "ai": ai_meta})
                return
            payload = _build_policy_outlook(events)
            payload["items"], ai_meta = _ai_rewrite_items("policy", payload["items"], ai_enabled)
            payload["ai"] = ai_meta
            self._send_json(payload)
            return

        # ── Sentiment feed ────────────────────────────────────────────────────
        if path == "/api/sentiment-feed":
            query = parse_qs(parsed.query)
            keyword = (query.get("keyword", ["ai regulation"]) or ["ai regulation"])[0]
            days = int((query.get("days", ["180"]) or ["180"])[0])
            limit = int((query.get("limit", ["20"]) or ["20"])[0])
            ai_enabled = _wants_ai(query)
            try:
                events = _load_events(keyword=keyword, days=days, limit=limit)
            except Exception as exc:
                events = _sample_events()
                deterministic = _build_sentiment_feed(events)
                rewritten_items, ai_meta = _ai_rewrite_items("sentiment", deterministic["items"], ai_enabled)
                self._send_json({"items": rewritten_items, "updated_at": _now_utc().isoformat(), "warning": f"Fallback sample data used: {exc}", "ai": ai_meta})
                return
            payload = _build_sentiment_feed(events)
            payload["items"], ai_meta = _ai_rewrite_items("sentiment", payload["items"], ai_enabled)
            payload["ai"] = ai_meta
            self._send_json(payload)
            return

        return super().do_GET()

    # ── POST ────────────────────────────────────────────────────────────────────

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Read request body
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
            body: dict[str, Any] = json.loads(body_bytes) if body_bytes.strip() else {}
        except Exception:
            body = {}

        # ── Screener start ────────────────────────────────────────────────────
        if path == "/api/screener/start":
            market = (body.get("market") or "SP500").strip().upper()
            valid = {"SP500", "NASDAQ100", "DAX40", "TW50", "CN_CSI300", "CN_SZ100", "CN_GEM", "CN_STAR"}
            if market not in valid:
                self._send_json({"error": f"Invalid market: {market!r}"}, 400)
                return
            job_id = str(uuid.uuid4())
            _SCREENER_JOBS[job_id] = {
                "status": "done",
                "market": market,
                "total": 0,
                "done": 0,
                "pct": 100,
                "passing": [],
                "scanning": [],
                "date_range": {},
                "from_cache": False,
                "rate_limited": False,
                "rate_limited_source": None,
                "error": None,
            }
            self._send_json({"job_id": job_id, "status": "done"})
            return

        # ── Screener control (pause / resume / cancel) ────────────────────────
        if re.match(r"^/api/screener/(pause|resume|cancel)/", path):
            self._send_json({"ok": True})
            return

        # ── Supply chain discover ─────────────────────────────────────────────
        if path == "/api/supply_chain/discover":
            ticker = (body.get("ticker") or "").upper()
            try:
                from services.supply_chain.graph import discover_supply_chain
                result = discover_supply_chain(ticker, lang=body.get("lang", "en"))
                self._send_json(result)
            except Exception as exc:
                self._send_json({"ticker": ticker, "nodes": [], "edges": [], "warning": str(exc)})
            return

        # ── Supply chain analyze node ─────────────────────────────────────────
        if path == "/api/supply_chain/analyze_node":
            try:
                from services.supply_chain.analyzer import analyze_node
                result = analyze_node(body.get("node_id", ""), lang=body.get("lang", "en"))
                self._send_json(result)
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
            return

        # ── Financial health summary / drilldown ──────────────────────────────
        if path in ("/api/financial_health/summary", "/api/financial_health/drilldown"):
            ticker = (body.get("ticker") or "").upper()
            self._send_json({"ticker": ticker, "summary": "", "warning": "LLM summary not available in lite server"})
            return

        # ── Backlog refresh ───────────────────────────────────────────────────
        if path == "/api/backlog/refresh":
            self._send_json({"ok": True, "refreshed": 0, "warning": "Backlog refresh not available in lite server"})
            return

        # ── Analyze (investment agent) ────────────────────────────────────────
        if path == "/api/analyze":
            self._send_json({"error": "Investment analysis requires LLM configuration"}, 503)
            return

        # ── Default 404 ───────────────────────────────────────────────────────
        self._send_json({"error": f"POST {path} not found"}, 404)


def run() -> None:
    import os
    port = int(os.getenv("PORT", "5501"))
    server = ThreadingHTTPServer(("0.0.0.0", port), UiApiHandler)
    print(f"UI + API server running at http://0.0.0.0:{port}/index.html")
    print("Endpoints: /api/policy-outlook, /api/sentiment-feed, /api/health,")
    print("           /api/exchange-rate, /api/tw/chips/*, /api/financial_health/data,")
    print("           /api/screener/start, /api/supply_chain/discover")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
