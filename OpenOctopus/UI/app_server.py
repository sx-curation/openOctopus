from __future__ import annotations

import json
import re
import sys
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


def _wants_ai(query: dict[str, list[str]]) -> bool:
    raw = (query.get("ai", ["off"]) or ["off"])[0].strip().lower()
    return raw in {"on", "1", "true", "yes"}




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

    # Limit items sent to AI to avoid token overflow; take most recent/important ones
    items_to_rewrite = items[:8]
    # Estimate tokens: ~120 tokens per item output, plus prompt overhead
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
        # Accept partial rewrites: at least half the items must be returned
        if rewritten and len(rewritten) >= max(1, len(items_to_rewrite) // 2):
            # Pad with originals if AI returned fewer items, then append any remaining original items beyond the slice
            merged = rewritten + items_to_rewrite[len(rewritten):]
            merged += items[len(items_to_rewrite):]  # append originals not sent to AI
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

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/policy-outlook":
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

        if parsed.path == "/api/sentiment-feed":
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


def run() -> None:
    port = 5501
    server = ThreadingHTTPServer(("0.0.0.0", port), UiApiHandler)
    print(f"UI + API server running at http://0.0.0.0:{port}/index.html")
    print("Endpoints: /api/policy-outlook, /api/sentiment-feed")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
