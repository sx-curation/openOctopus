"""
Policy Monitoring Agent — AI-powered implementation.

Two modes of operation:
  1. run_analysis(query)  — TRUE AI AGENT: LLM drives tool selection and synthesis
  2. query_updates(...)   — PROGRAMMATIC: direct API fetch without LLM (for use as a tool
                            inside the investment analysis agent)

The LLM-powered mode uses the same client/backend configured in .env
(Azure OpenAI / OpenAI / Ollama / any OpenAI-compatible endpoint).
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import List, Optional

from openai import AzureOpenAI, OpenAI, APITimeoutError

from config import settings
from agent.policy_monitoring.digest import generate_digest as _render_digest
from agent.policy_monitoring.rules import classify_impact as _classify
from agent.policy_monitoring.rules import detect_topics
from agent.policy_monitoring.schemas import DiffSummary, ImpactClassification, PolicyEvent
from agent.policy_monitoring.system_prompt import POLICY_SYSTEM_PROMPT
from tools.policy_sources import eurlex, federal_register, sec_edgar
from tools.policy_sources.cache import DiskCache
from tools.policy_sources.http_client import PolicyHttpClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions for the LLM (agentic loop)
# ---------------------------------------------------------------------------

_POLICY_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "fetch_eurlex",
            "description": (
                "Search EU legislation in EUR-Lex via the Publications Office SPARQL endpoint. "
                "Returns EU Regulations, Directives, Decisions and Notices matching the keyword "
                "within the given date range."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Search term, e.g. 'AI Act', 'DORA', 'crypto'"},
                    "from_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "to_date":   {"type": "string", "description": "End date YYYY-MM-DD"},
                    "limit":     {"type": "integer", "description": "Max results (default 10)", "default": 10},
                },
                "required": ["keyword", "from_date", "to_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_federal_register",
            "description": (
                "Search the US Federal Register for final rules, proposed rules and agency notices. "
                "Returns official US regulatory documents published within the given date range."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Search term, e.g. 'AI governance', 'crypto', 'tariff'"},
                    "from_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "to_date":   {"type": "string", "description": "End date YYYY-MM-DD"},
                    "limit":     {"type": "integer", "description": "Max results (default 10)", "default": 10},
                },
                "required": ["keyword", "from_date", "to_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_sec_edgar",
            "description": (
                "Search SEC EDGAR full-text search for regulatory filings, rule releases, "
                "concept releases and staff guidance. Use this for US securities law and "
                "financial regulation topics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Search term, e.g. 'climate disclosure', 'digital assets'"},
                    "from_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "to_date":   {"type": "string", "description": "End date YYYY-MM-DD"},
                    "limit":     {"type": "integer", "description": "Max results (default 10)", "default": 10},
                },
                "required": ["keyword", "from_date", "to_date"],
            },
        },
    },
]

MAX_ITERATIONS = 10


# ---------------------------------------------------------------------------
# Build LLM client (mirrors agent/loop.py — same .env, same backend)
# ---------------------------------------------------------------------------

def _build_llm_client():
    if settings.AZURE_OPENAI_ENDPOINT:
        return AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )
    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.BASE_URL or None,
    )


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class PolicyMonitoringAgent:
    """
    AI-powered Policy Monitoring Agent.

    run_analysis(query) — TRUE AI AGENT powered by your configured LLM.
    query_updates(...)  — direct programmatic fetch (no LLM).
    """

    SOURCE_ALL = ["EUR_LEX", "FEDERAL_REGISTER", "SEC"]

    def __init__(self):
        self._llm = _build_llm_client()
        self._http = PolicyHttpClient(
            user_agent=settings.POLICY_USER_AGENT,
            timeout=settings.POLICY_HTTP_TIMEOUT,
            retries=settings.POLICY_HTTP_RETRIES,
            backoff_base=settings.POLICY_HTTP_BACKOFF,
        )
        self._cache = DiskCache(
            cache_dir=settings.POLICY_CACHE_DIR,
            ttl_seconds=settings.POLICY_CACHE_TTL,
        )

    # ------------------------------------------------------------------
    # TRUE AI AGENT — LLM drives the analysis
    # ------------------------------------------------------------------

    def run_analysis(self, user_query: str) -> str:
        """
        Run a policy intelligence query using the configured LLM.

        The LLM decides which sources to query, calls the fetch tools,
        and synthesises a structured report — exactly like the investment
        analysis agent, but focused on regulatory intelligence.

        Args:
            user_query: Natural language question, e.g.
                "What EU AI regulations were published in 2024?"
                "Any SEC rules on crypto custody in the last 6 months?"

        Returns:
            Markdown report string.
        """
        messages = [
            {"role": "system", "content": POLICY_SYSTEM_PROMPT},
            {"role": "user",   "content": user_query},
        ]
        iterations = 0

        while iterations < MAX_ITERATIONS:
            try:
                response = self._llm.chat.completions.create(
                    model=settings.MODEL,
                    tools=_POLICY_TOOL_DEFINITIONS,
                    messages=messages,
                    max_tokens=4096,
                    timeout=settings.API_TIMEOUT,
                )
            except APITimeoutError:
                raise TimeoutError(
                    f"模型 '{settings.MODEL}' 沒有回應（{settings.API_TIMEOUT}s）。"
                    "請確認服務是否正在執行。"
                )
            iterations += 1

            choice = response.choices[0]

            if choice.finish_reason == "stop":
                return choice.message.content or ""

            if choice.finish_reason == "tool_calls":
                messages.append(choice.message)

                # Execute all tool calls in parallel
                tool_calls = choice.message.tool_calls
                with ThreadPoolExecutor(max_workers=len(tool_calls)) as executor:
                    futures = {
                        executor.submit(self._dispatch_tool, tc.function.name,
                                        json.loads(tc.function.arguments)): tc
                        for tc in tool_calls
                    }
                    for future in as_completed(futures):
                        tc = futures[future]
                        try:
                            result = future.result()
                        except Exception as exc:
                            result = {"error": str(exc)}
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result, default=str),
                        })
                continue

            break  # unexpected finish_reason

        return "Policy analysis incomplete: maximum iterations reached."

    # ------------------------------------------------------------------
    # Tool dispatcher (for the agentic loop above)
    # ------------------------------------------------------------------

    def _dispatch_tool(self, name: str, args: dict) -> dict:
        """Execute a policy fetch tool and return serialisable results."""
        keyword   = args["keyword"]
        from_date = args.get("from_date", "2024-01-01")
        to_date   = args.get("to_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        limit     = int(args.get("limit", 10))

        if name == "fetch_eurlex":
            raw = eurlex.fetch_raw(self._http, keyword, from_date, to_date, limit)
            events = eurlex.normalize(raw)
        elif name == "fetch_federal_register":
            raw = federal_register.fetch_raw(self._http, keyword, from_date, to_date, limit)
            events = federal_register.normalize(raw)
        elif name == "fetch_sec_edgar":
            raw = sec_edgar.fetch_raw(self._http, keyword, from_date, to_date, limit)
            events = sec_edgar.normalize(raw)
        else:
            return {"error": f"Unknown tool: {name}"}

        return {
            "count": len(events),
            "events": [e.to_dict() for e in events],
        }

    # ------------------------------------------------------------------
    # PROGRAMMATIC MODE — direct fetch, no LLM
    # ------------------------------------------------------------------

    def query_updates(
        self,
        jurisdiction: str,
        keyword: str,
        from_date: str | datetime,
        to_date: str | datetime,
        limit: int = 20,
        sources: Optional[List[str]] = None,
    ) -> List[PolicyEvent]:
        """
        Directly fetch and normalise policy events (no LLM).
        Used by the investment analysis agent as a tool.
        """
        from_str = from_date.strftime("%Y-%m-%d") if isinstance(from_date, datetime) else from_date
        to_str   = to_date.strftime("%Y-%m-%d")   if isinstance(to_date,   datetime) else to_date

        active_sources = [s.upper() for s in (sources or self.SOURCE_ALL)]
        jur_upper = jurisdiction.upper()
        if jur_upper == "EU":
            active_sources = [s for s in active_sources if s == "EUR_LEX"]
        elif jur_upper == "US":
            active_sources = [s for s in active_sources if s in ("FEDERAL_REGISTER", "SEC")]

        events: list[PolicyEvent] = []
        for source in active_sources:
            cache_params = {"source": source, "keyword": keyword, "from": from_str, "to": to_str, "limit": limit}
            cached = self._cache.get(f"query_updates:{source}", cache_params)
            if cached is not None:
                events.extend([PolicyEvent(**e) for e in cached])
                continue
            try:
                raw_events = self._fetch_source(source, keyword, from_str, to_str, limit)
                self._cache.set(f"query_updates:{source}", cache_params, [e.to_dict() for e in raw_events])
                events.extend(raw_events)
            except Exception as exc:
                logger.error("policy_monitor: source=%s error=%s", source, exc)

        for ev in events:
            if not ev.topics:
                ev.topics = detect_topics(ev.title + " " + ev.summary)

        events.sort(key=lambda e: e.published_at, reverse=True)
        return events

    def classify_impact(self, event: PolicyEvent) -> ImpactClassification:
        """Keyword-rule based impact classification (no LLM)."""
        return _classify(event)

    def generate_digest(
        self,
        events: List[PolicyEvent],
        fmt: str = "md",
        title: str = "Policy Monitoring Digest",
    ) -> str:
        """Render events as a Markdown digest with source URLs."""
        classifications = [self.classify_impact(ev) for ev in events]
        return _render_digest(events, classifications=classifications, title=title)

    def compare_versions(self, source: str, source_doc_id: str) -> DiffSummary:
        """Compare cached snapshot vs live version (metadata diff)."""
        snapshot_key = f"snapshot:{source}:{source_doc_id}"
        old_data = self._cache.get(snapshot_key, {})
        fresh = self.query_updates("ALL", source_doc_id, "1900-01-01",
                       datetime.now(timezone.utc).strftime("%Y-%m-%d"), limit=1, sources=[source])
        new_data = fresh[0].to_dict() if fresh else None
        if new_data:
            self._cache.set(snapshot_key, {}, new_data)
        if not old_data or not new_data:
            return DiffSummary(source=source, source_doc_id=source_doc_id,
                               old_version=old_data, new_version=new_data,
                               note="No prior snapshot — storing current as baseline.")
        fields = ["title", "summary", "effective_from", "effective_to", "jurisdictions", "regulator", "topics", "relationships"]
        changed = [f for f in fields if old_data.get(f) != new_data.get(f)]
        return DiffSummary(source=source, source_doc_id=source_doc_id,
                           old_version=old_data, new_version=new_data,
                           changed_fields=changed,
                           title_changed="title" in changed,
                           summary_changed="summary" in changed,
                           note=f"Full text: {new_data.get('fulltext_url', 'N/A')}")

    def _fetch_source(self, source, keyword, from_str, to_str, limit):
        if source == "EUR_LEX":
            return eurlex.normalize(eurlex.fetch_raw(self._http, keyword, from_str, to_str, limit))
        if source == "FEDERAL_REGISTER":
            return federal_register.normalize(federal_register.fetch_raw(self._http, keyword, from_str, to_str, limit))
        if source == "SEC":
            return sec_edgar.normalize(sec_edgar.fetch_raw(self._http, keyword, from_str, to_str, limit))
        raise ValueError(f"Unknown source: {source!r}")
