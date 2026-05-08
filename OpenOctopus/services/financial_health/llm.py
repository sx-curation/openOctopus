"""Financial Health LLM Analyzer.

Two analysis modes:
1. health_summary() — concise overall health assessment + strengths/weaknesses
2. drilldown_analysis() — 5-section deep-dive (revenue, GM, OpEx, FCF, guidance)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_TRANSCRIPT_CHARS = 6000

# ── System prompts ─────────────────────────────────────────────────────────

_SUMMARY_PROMPTS = {
    "en": (
        "You are an institutional equity analyst. Based on the provided financial metrics, "
        "write a 3-sentence overall financial health assessment, then list 3-5 key STRENGTHS "
        "and 3-5 key WEAKNESSES as concise bullet points (max 20 words each, citing specific numbers). "
        "Return ONLY valid JSON: "
        '{"summary": "...", "strengths": ["...", "..."], "weaknesses": ["...", "..."]} '
        "No markdown, no extra text."
    ),
    "de": (
        "Sie sind ein institutioneller Aktienanalyst. Analysieren Sie die bereitgestellten Kennzahlen. "
        "Schreiben Sie eine 3-seitige Gesamtbewertung, dann 3-5 STÄRKEN und 3-5 SCHWÄCHEN "
        "als prägnante Bullet-Points (max. 20 Wörter, mit konkreten Zahlen). "
        "Geben Sie NUR gültiges JSON zurück: "
        '{"summary": "...", "strengths": ["..."], "weaknesses": ["..."]} '
        "Kein Markdown."
    ),
    "zh": (
        "你是一位機構股票分析師。根據提供的財務指標，"
        "撰寫 3 句話的整體財務健康評估，然後列出 3-5 個關鍵優勢和 3-5 個關鍵弱點，"
        "每項用一句話（最多 20 字，引用具體數字）。"
        "只回傳合法 JSON："
        '{"summary": "...", "strengths": ["...", "..."], "weaknesses": ["...", "..."]} '
        "不加任何 markdown 或解釋。"
    ),
}

_DRILLDOWN_PROMPTS = {
    "en": (
        "You are an institutional equity analyst. Analyze the provided financial data"
        "{transcript_clause} across these 5 sections:\n"
        "1. Revenue Growth Drivers (pricing vs volume, mix shifts)\n"
        "2. Gross Margin Source (expansion/compression drivers)\n"
        "3. Operating Leverage (opex vs revenue growth)\n"
        "4. Free Cash Flow Quality (OCF conversion, capex trends)\n"
        "5. Forward Guidance Signal (outlook, guidance delta vs prior)\n"
        "Each section: 2-3 concise sentences with specific numbers where possible. "
        "Classify each as POSITIVE, NEUTRAL, or NEGATIVE. "
        "Return ONLY valid JSON: "
        '{{"sections": [{{"title": "...", "content": "...", "sentiment": "positive|neutral|negative"}}, ...]}} '
        "No markdown, no extra text."
    ),
    "de": (
        "Sie sind ein institutioneller Aktienanalyst. Analysieren Sie die Finanzdaten"
        "{transcript_clause} in diesen 5 Bereichen:\n"
        "1. Umsatzwachstumstreiber\n2. Bruttomargenquelle\n3. Operating Leverage\n"
        "4. Free Cashflow Qualität\n5. Guidance-Signal\n"
        "Jeder Abschnitt: 2-3 präzise Sätze mit Zahlen. Klassifizieren Sie als POSITIVE, NEUTRAL oder NEGATIVE. "
        "Geben Sie NUR gültiges JSON zurück: "
        '{{"sections": [{{"title": "...", "content": "...", "sentiment": "positive|neutral|negative"}}, ...]}} '
        "Kein Markdown."
    ),
    "zh": (
        "你是一位機構股票分析師。分析提供的財務數據"
        "{transcript_clause}，涵蓋以下 5 個面向：\n"
        "1. 營收成長驅動因素（定價 vs 量能，產品組合）\n"
        "2. 毛利擴張/壓縮來源\n"
        "3. 運營槓桿（營業費用 vs 營收成長）\n"
        "4. 自由現金流品質（OCF 轉換率、資本支出趨勢）\n"
        "5. 前瞻指引信號（展望、vs 前次指引差異）\n"
        "每個面向 2-3 句話，盡量引用具體數字，分類為 POSITIVE / NEUTRAL / NEGATIVE。"
        "只回傳合法 JSON："
        '{{"sections": [{{"title": "...", "content": "...", "sentiment": "positive|neutral|negative"}}, ...]}} '
        "不加 markdown 或解釋。"
    ),
}

_TRANSCRIPT_CLAUSES = {
    "en": " and the latest earnings call transcript",
    "de": " und dem neuesten Earnings-Call-Transkript",
    "zh": "及最新法說會逐字稿",
}


# ── Helpers ────────────────────────────────────────────────────────────────

def _fmt_metric(name: str, values: List, years: List[int]) -> str:
    """Format a single metric row as a readable string for the prompt."""
    parts = []
    for i, y in enumerate(years[:4]):
        v = values[i] if i < len(values) else None
        if v is None:
            parts.append(f"{y}: N/A")
            continue
        try:
            fv = float(v)
            # Percent metrics
            if any(k in name.lower() for k in ("growth", "margin", "ratio", "roe", "roic", "equity", "return")):
                parts.append(f"{y}: {fv*100:.1f}%")
            elif abs(fv) > 1e9:
                parts.append(f"{y}: {fv/1e9:.2f}B")
            elif abs(fv) > 1e6:
                parts.append(f"{y}: {fv/1e6:.1f}M")
            else:
                parts.append(f"{y}: {fv:.2f}")
        except Exception:
            parts.append(f"{y}: {v}")
    return f"  {name}: {', '.join(parts)}"


def _build_metrics_block(funda: Dict[str, List], years: List[int]) -> str:
    """Build a compact text block of key metrics for LLM context."""
    key_metrics = [
        "revenueGrowth", "grossProfitMargin", "operatingCashFlowToNetIncome",
        "epsgrowth", "freeCashFlowGrowth", "returnOnEquity", "returnOnInvestedCapital",
        "interestCoverage", "DebtToEquity", "actualDebtRatio", "currentRatio",
        "capitalExpenditure_growth_yoy", "netInterestIncome",
        "revenue", "netIncome", "freeCashFlow",
    ]
    lines = ["Financial Metrics (newest first):"]
    for m in key_metrics:
        vals = funda.get(m)
        if vals:
            lines.append(_fmt_metric(m, vals, years))
    return "\n".join(lines)


def _parse_llm_json(raw: str) -> Optional[Dict]:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        return None


# ── health_summary ─────────────────────────────────────────────────────────

def health_summary(
    ticker: str,
    funda: Dict[str, List],
    years: List[int],
    scores: Dict[str, Any],
    lang: str = "en",
) -> Dict[str, Any]:
    """Generate a concise financial health summary using the LLM.

    Returns: {summary, strengths, weaknesses, error}
    """
    from agent.llm_client import get_llm_client
    from config import settings

    metrics_block = _build_metrics_block(funda, years)
    score_line = f"\nWeighted Health Score: {scores.get('weighted_100', 'N/A')}/100"
    user_content = f"Ticker: {ticker}\n{score_line}\n\n{metrics_block}"

    system_prompt = _SUMMARY_PROMPTS.get(lang, _SUMMARY_PROMPTS["en"])

    try:
        client = get_llm_client()
        response = client.chat.completions.create(
            model=settings.MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=600,
        )
        raw = response.choices[0].message.content or ""
    except Exception as e:
        logger.warning("health_summary LLM error for %s: %s", ticker, e)
        return {"summary": "", "strengths": [], "weaknesses": [], "error": str(e)}

    parsed = _parse_llm_json(raw)
    if not parsed:
        return {"summary": raw[:300], "strengths": [], "weaknesses": [], "error": "JSON parse failed"}

    return {
        "summary": parsed.get("summary") or "",
        "strengths": parsed.get("strengths") or [],
        "weaknesses": parsed.get("weaknesses") or [],
        "error": None,
    }


# ── drilldown_analysis ─────────────────────────────────────────────────────

def drilldown_analysis(
    ticker: str,
    funda: Dict[str, List],
    years: List[int],
    transcript_excerpt: Optional[str] = None,
    lang: str = "en",
) -> Dict[str, Any]:
    """Generate 5-section contribution drill-down using the LLM.

    Returns: {sections: [{title, content, sentiment}], error}
    """
    from agent.llm_client import get_llm_client
    from config import settings

    metrics_block = _build_metrics_block(funda, years)
    has_transcript = bool(transcript_excerpt and transcript_excerpt.strip())

    transcript_clause = _TRANSCRIPT_CLAUSES.get(lang, _TRANSCRIPT_CLAUSES["en"]) if has_transcript else ""
    system_prompt = _DRILLDOWN_PROMPTS.get(lang, _DRILLDOWN_PROMPTS["en"]).format(
        transcript_clause=transcript_clause
    )

    user_content = f"Ticker: {ticker}\n\n{metrics_block}"
    if has_transcript:
        excerpt = transcript_excerpt[:_MAX_TRANSCRIPT_CHARS]  # type: ignore[index]
        user_content += f"\n\nLatest Earnings Call Excerpt:\n{excerpt}"

    try:
        client = get_llm_client()
        response = client.chat.completions.create(
            model=settings.MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=1200,
        )
        raw = response.choices[0].message.content or ""
    except Exception as e:
        logger.warning("drilldown_analysis LLM error for %s: %s", ticker, e)
        return {"sections": [], "error": str(e)}

    parsed = _parse_llm_json(raw)
    if not parsed:
        return {"sections": [], "error": "JSON parse failed"}

    sections = parsed.get("sections") or []
    # Normalize sentiment
    for sec in sections:
        s = str(sec.get("sentiment", "neutral")).lower()
        sec["sentiment"] = s if s in ("positive", "negative", "neutral") else "neutral"

    return {"sections": sections, "error": None}
