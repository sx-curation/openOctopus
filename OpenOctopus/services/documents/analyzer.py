"""Document transcript analyzer.

Analyzes a cached earnings transcript using the LLM and returns
positive signals (alpha) and negative signals (beta risks) as bullet-point lists.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_MAX_CONTENT_CHARS = 8000

_SYSTEM_PROMPTS = {
    "en": (
        "You are an institutional financial analyst. Analyze the following earnings call transcript "
        "and extract 3 to 5 concrete POSITIVE SIGNALS (alpha opportunities: specific revenue growth, "
        "margin expansion, new product launches, bullish guidance, strong demand signals) and "
        "3 to 5 concrete NEGATIVE SIGNALS (beta risks: margin pressure, demand slowdown, competitive threats, "
        "guidance cuts, cost headwinds, macro concerns raised by management). "
        "Each signal must be a single concise sentence (max 25 words) citing a specific number, "
        "metric, or management quote where possible. "
        "Return ONLY valid JSON in this exact format: "
        '{\"positive_signals\": [\"...\", \"...\"], \"negative_signals\": [\"...\", \"...\"]} '
        "No markdown, no explanations, no extra text."
    ),
    "de": (
        "Sie sind ein institutioneller Finanzanalyst. Analysieren Sie das folgende Earnings-Call-Transkript "
        "und extrahieren Sie 3 bis 5 konkrete POSITIVE SIGNALE (Alpha-Chancen: Umsatzwachstum, "
        "Margenausweitung, neue Produkte, optimistischer Ausblick, starke Nachfragesignale) und "
        "3 bis 5 konkrete NEGATIVE SIGNALE (Beta-Risiken: Margendruck, Nachfragerückgang, "
        "Wettbewerbsbedrohungen, Guidancekürzungen, Kostenbelastungen). "
        "Jedes Signal ist ein präziser Satz mit maximal 25 Wörtern. "
        "Geben Sie NUR gültiges JSON zurück: "
        '{\"positive_signals\": [\"...\"], \"negative_signals\": [\"...\"]} '
        "Keine Erklärungen, kein Markdown."
    ),
    "zh": (
        "你是一位機構級財報分析師。分析以下法說會逐字稿，"
        "提取 3 至 5 個具體的正面信號（Alpha 機會：具體營收成長、毛利擴張、新品發布、"
        "上調指引、強勁需求信號）和 3 至 5 個具體的負面信號（Beta 風險：毛利壓力、"
        "需求放緩、競爭威脅、下調指引、成本逆風、管理層提及的宏觀憂慮）。"
        "每個信號為一句話（最多 25 字），盡量引用具體數字或管理層話語。"
        "只回傳合法 JSON，格式如下："
        '{"positive_signals": ["...", "..."], "negative_signals": ["...", "..."]} '
        "不加任何解釋或 markdown。"
    ),
}


def analyze_transcript(
    ticker: str,
    year: int | None,
    quarter: int | None,
    lang: str = "en",
) -> dict:
    """Analyze an earnings transcript and return positive/negative signals.

    Returns:
        dict with keys: positive_signals (list[str]), negative_signals (list[str]),
        ticker, period. On failure: adds 'error' key.
    """
    from data_sources.transcripts.hf_cache import get_cached_transcript
    from agent.llm_client import get_llm_client
    from config import settings

    t = ticker.upper()
    period = f"Q{quarter} {year}" if year and quarter else "unknown"

    # Fetch transcript content from HF cache
    cached = get_cached_transcript(t, year=year, quarter=quarter)
    if "error" in cached:
        return {
            "ticker": t, "period": period,
            "positive_signals": [], "negative_signals": [],
            "error": f"Transcript not found: {cached['error']}",
        }

    content = (cached.get("content_excerpt") or cached.get("content") or "").strip()
    if not content:
        return {
            "ticker": t, "period": period,
            "positive_signals": [], "negative_signals": [],
            "error": "Transcript content is empty.",
        }

    # Truncate to avoid token limit
    truncated = content[:_MAX_CONTENT_CHARS]

    system_prompt = _SYSTEM_PROMPTS.get(lang, _SYSTEM_PROMPTS["en"])

    try:
        client = get_llm_client()
        response = client.chat.completions.create(
            model=settings.MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": truncated},
            ],
            temperature=0.2,
            max_tokens=800,
        )
        raw = response.choices[0].message.content or ""
    except Exception as e:
        logger.warning("doc analyzer: LLM call failed for %s %s: %s", t, period, e)
        return {
            "ticker": t, "period": period,
            "positive_signals": [], "negative_signals": [],
            "error": str(e),
        }

    # Parse LLM response as JSON — handles prose/fences from local models
    import re as _re
    raw = raw.strip()
    parsed = None
    for _attempt in [
        lambda r: json.loads(r),
        lambda r: json.loads(_re.search(r"```(?:json)?\s*(\{.*?\})\s*```", r, _re.DOTALL).group(1)),
        lambda r: json.loads(r[r.find("{"):r.rfind("}") + 1]) if r.find("{") != -1 else (_ for _ in ()).throw(ValueError()),
    ]:
        try:
            parsed = _attempt(raw)
            break
        except Exception:
            continue

    if parsed is None:
        logger.warning("doc analyzer: JSON parse failed for %s %s | raw: %r", t, period, raw[:200])
        return {
            "ticker": t, "period": period,
            "positive_signals": [], "negative_signals": [],
            "error": "LLM returned invalid JSON",
        }

    return {
        "ticker": t,
        "period": period,
        "positive_signals": parsed.get("positive_signals") or [],
        "negative_signals": parsed.get("negative_signals") or [],
        "error": None,
    }
