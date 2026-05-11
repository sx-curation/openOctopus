"""Supply Chain Node Analyzer.

When a user clicks a node in the supply chain graph, this module uses the LLM
to generate a deep-dive read-through analysis for that specific company,
incorporating cached transcript excerpts and financial metrics where available.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_TRANSCRIPT_CHARS = 4000

# ── Prompts ────────────────────────────────────────────────────────────────────

_ANALYZE_PROMPTS = {
    "en": (
        "You are an institutional equity analyst specializing in supply chain read-through. "
        "The anchor company is {center} ({center_name}). "
        "Analyze the earnings read-through impact on {node} ({node_name}), "
        "which is a {relation} of {center}.\n\n"
        "{context_block}"
        "Provide:\n"
        "1. impact_direction: 'positive', 'neutral', or 'negative'\n"
        "2. summary: 2-3 sentences on the direct earnings read-through\n"
        "3. capex_signal: 1 sentence on CAPEX/investment implications (if applicable)\n"
        "4. signals: list of 3-5 key signals (bullish or bearish) as short bullet points\n\n"
        "Return ONLY valid JSON (no markdown):\n"
        '{{"impact_direction": "positive|neutral|negative", '
        '"summary": "...", '
        '"capex_signal": "...", '
        '"signals": ["...", "..."]}}'
    ),
    "de": (
        "Sie sind ein institutioneller Aktienanalyst für Lieferketten-Read-through. "
        "Das Ankerunternehmen ist {center} ({center_name}). "
        "Analysieren Sie den Earnings-Read-through-Effekt auf {node} ({node_name}), "
        "ein {relation}-Unternehmen von {center}.\n\n"
        "{context_block}"
        "Liefern Sie:\n"
        "1. impact_direction: 'positive', 'neutral' oder 'negative'\n"
        "2. summary: 2-3 Sätze zum Read-through\n"
        "3. capex_signal: 1 Satz zu CAPEX-Implikationen\n"
        "4. signals: 3-5 Stichpunkte (bullish/bearish)\n\n"
        "Geben Sie NUR gültiges JSON zurück:\n"
        '{{"impact_direction": "...", "summary": "...", "capex_signal": "...", "signals": ["..."]}}'
    ),
    "zh": (
        "你是一位專注供應鏈讀穿分析的機構股票分析師。"
        "錨定公司為 {center}（{center_name}）。"
        "分析其財報對 {node}（{node_name}，{center} 的{relation}）的讀穿影響。\n\n"
        "{context_block}"
        "請提供：\n"
        "1. impact_direction：'positive'、'neutral' 或 'negative'\n"
        "2. summary：2-3 句描述直接讀穿影響\n"
        "3. capex_signal：1 句說明資本支出/投資含義（如適用）\n"
        "4. signals：3-5 個關鍵信號（看多或看空）的簡短要點\n\n"
        "只回傳合法 JSON（不加 markdown）：\n"
        '{{"impact_direction": "positive|neutral|negative", '
        '"summary": "...", '
        '"capex_signal": "...", '
        '"signals": ["...", "..."]}}'
    ),
}

_RELATION_LABELS = {
    "en": {"upstream": "upstream supplier", "downstream": "downstream customer", "peer": "peer/competitor"},
    "de": {"upstream": "Lieferant", "downstream": "Kunde", "peer": "Wettbewerber"},
    "zh": {"upstream": "上游供應商", "downstream": "下游客戶", "peer": "同業/競爭對手"},
}


def _parse_json(raw: str) -> Optional[Dict]:
    """Extract and parse the first JSON object from a raw LLM response.

    Handles: plain JSON, markdown code fences, prose before/after JSON.
    """
    import re
    raw = raw.strip()

    # 1. Try direct parse first
    try:
        return json.loads(raw)
    except Exception:
        pass

    # 2. Extract from markdown code fence
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:
            pass

    # 3. Find first { and last } — handles prose before/after JSON
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            pass

    return None


def _build_context_block(
    transcript_excerpt: Optional[str],
    financial_summary: Optional[str],
    lang: str,
) -> str:
    parts = []
    if financial_summary:
        header = {
            "en": "Key Financial Metrics (anchor company):",
            "de": "Wichtige Finanzkennzahlen (Ankerunternehmen):",
            "zh": "關鍵財務指標（錨定公司）：",
        }.get(lang, "Key Financial Metrics:")
        parts.append(f"{header}\n{financial_summary}\n")
    if transcript_excerpt:
        header = {
            "en": "Latest Earnings Call Excerpt (anchor company):",
            "de": "Neuester Earnings-Call-Auszug (Ankerunternehmen):",
            "zh": "最新法說會摘錄（錨定公司）：",
        }.get(lang, "Earnings Call Excerpt:")
        excerpt = transcript_excerpt[:_MAX_TRANSCRIPT_CHARS]
        parts.append(f"{header}\n{excerpt}\n")
    return "\n".join(parts) + "\n" if parts else ""


def analyze_node(
    center_ticker: str,
    center_name: str,
    node_ticker: str,
    node_name: str,
    relation: str,
    transcript_excerpt: Optional[str] = None,
    financial_summary: Optional[str] = None,
    lang: str = "en",
) -> Dict[str, Any]:
    """Generate LLM read-through analysis for a supply chain node.

    Returns:
        {impact_direction, summary, capex_signal, signals, error}
    """
    from agent.llm_client import get_llm_client
    from config import settings

    relation_label = _RELATION_LABELS.get(lang, _RELATION_LABELS["en"]).get(relation, relation)
    context_block = _build_context_block(transcript_excerpt, financial_summary, lang)

    prompt_tpl = _ANALYZE_PROMPTS.get(lang, _ANALYZE_PROMPTS["en"])
    prompt = (
        prompt_tpl
        .replace("{center}", center_ticker.upper())
        .replace("{center_name}", center_name)
        .replace("{node}", node_ticker.upper())
        .replace("{node_name}", node_name)
        .replace("{relation}", relation_label)
        .replace("{context_block}", context_block)
    )

    try:
        client = get_llm_client()
        response = client.chat.completions.create(
            model=settings.MODEL,
            messages=[
                {"role": "system", "content": "You are a financial analyst. You must respond with ONLY valid JSON, no explanatory text before or after. No markdown code fences. Output only the raw JSON object."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=700,
        )
        raw = response.choices[0].message.content or ""
    except Exception as e:
        logger.warning("analyze_node LLM error %s→%s: %s", center_ticker, node_ticker, e)
        return {"impact_direction": "neutral", "summary": "", "capex_signal": "", "signals": [], "error": str(e)}

    parsed = _parse_json(raw)
    if not parsed:
        return {"impact_direction": "neutral", "summary": raw[:300], "capex_signal": "", "signals": [], "error": "JSON parse failed"}

    direction = str(parsed.get("impact_direction") or "neutral").lower()
    if direction not in ("positive", "negative", "neutral"):
        direction = "neutral"

    return {
        "impact_direction": direction,
        "summary": str(parsed.get("summary") or ""),
        "capex_signal": str(parsed.get("capex_signal") or ""),
        "signals": list(parsed.get("signals") or []),
        "error": None,
    }
