"""Supply Chain Graph Discovery.

Uses the LLM to discover upstream suppliers and downstream customers for a
given company, and returns a structured graph (nodes + edges) suitable for
both a table view and an SVG network visualization.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2

# ── Prompts ────────────────────────────────────────────────────────────────────

_DISCOVER_PROMPTS = {
    "en": (
        "You are a supply chain analyst. For the company with ticker {ticker}, "
        "identify its supply chain ecosystem:\n"
        "- Tier-1 upstream suppliers (who supply key components/equipment/materials)\n"
        "- Tier-1 downstream customers (who buy its products/services)\n"
        "- Important peers/competitors if relevant\n"
        "- Deeper tier-2 nodes if meaningful (e.g. TSMC → ASML suppliers)\n\n"
        "For each related company, assess the read-through impact when {ticker} "
        "reports STRONG earnings (beat guidance, raised outlook, CAPEX increase):\n"
        "  +1 = positive (strong demand signal for them)\n"
        "   0 = neutral / indirect\n"
        "  -1 = negative (e.g. capacity competition)\n\n"
        "Return ONLY valid JSON (no markdown):\n"
        '{{"center": {{"ticker": "{ticker}", "name": "Full Company Name"}},\n'
        ' "nodes": [\n'
        '   {{"ticker": "XXXX", "name": "Company Name", '
        '"relation": "upstream|downstream|peer", '
        '"tier": 1, '
        '"direction": 1, '
        '"reason": "One sentence why this company is affected"}}\n'
        ' ],\n'
        ' "edges": [{{"source": "{ticker}", "target": "XXXX"}}]\n'
        "}}"
    ),
    "de": (
        "Sie sind ein Lieferkettenanalyst. Identifizieren Sie für das Unternehmen {ticker} "
        "sein Lieferkettenökosystem: Tier-1-Lieferanten (upstream), Tier-1-Kunden (downstream), "
        "wichtige Peers und ggf. Tier-2-Knoten.\n"
        "Bewerten Sie den Read-through-Effekt bei starken {ticker}-Ergebnissen:\n"
        "+1 = positiv, 0 = neutral, -1 = negativ.\n"
        "Geben Sie NUR gültiges JSON zurück (kein Markdown):\n"
        '{{"center": {{"ticker": "{ticker}", "name": "Vollständiger Name"}},\n'
        ' "nodes": [{{"ticker": "XXXX", "name": "Name", "relation": "upstream|downstream|peer", '
        '"tier": 1, "direction": 1, "reason": "Begründung"}}],\n'
        ' "edges": [{{"source": "{ticker}", "target": "XXXX"}}]}}'
    ),
    "zh": (
        "你是一位供應鏈分析師。針對公司 {ticker}，識別其供應鏈生態系統：\n"
        "- Tier-1 上游供應商（提供關鍵零組件/設備/原料）\n"
        "- Tier-1 下游客戶（購買其產品/服務）\n"
        "- 重要同業/競爭對手（如有意義）\n"
        "- 有意義的 Tier-2 節點（如 TSMC → ASML 的供應商）\n\n"
        "當 {ticker} 發布強勁財報（超預期、上調展望、增加 CAPEX）時，"
        "評估對各關聯公司的讀穿影響：\n"
        "  +1 = 利多（強勁需求信號）\n"
        "   0 = 中性/間接影響\n"
        "  -1 = 利空（如產能競爭）\n\n"
        "只回傳合法 JSON（不加 markdown）：\n"
        '{{"center": {{"ticker": "{ticker}", "name": "公司全名"}},\n'
        ' "nodes": [\n'
        '   {{"ticker": "XXXX", "name": "公司名稱", '
        '"relation": "upstream|downstream|peer", '
        '"tier": 1, '
        '"direction": 1, '
        '"reason": "一句話說明影響原因"}}\n'
        ' ],\n'
        ' "edges": [{{"source": "{ticker}", "target": "XXXX"}}]\n'
        "}}"
    ),
}


def _parse_json(raw: str) -> Optional[Dict]:
    """Extract and parse the first JSON object from a raw LLM response.

    Handles: plain JSON, markdown code fences, prose before/after JSON.
    """
    import re
    raw = raw.strip()

    # 1. Try direct parse first (already clean JSON)
    try:
        return json.loads(raw)
    except Exception:
        pass

    # 2. Extract from markdown code fence (```json ... ``` or ``` ... ```)
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


def discover_supply_chain(
    ticker: str,
    lang: str = "en",
) -> Dict[str, Any]:
    """Use LLM to discover supply chain nodes and edges for a given ticker.

    Returns:
        {
          center: {ticker, name},
          nodes: [{ticker, name, relation, tier, direction, reason}],
          edges: [{source, target}],
          error: None | str
        }
    """
    from agent.llm_client import get_llm_client
    from config import settings

    t = ticker.upper().strip()
    prompt_tpl = _DISCOVER_PROMPTS.get(lang, _DISCOVER_PROMPTS["en"])
    prompt = prompt_tpl.replace("{ticker}", t)

    try:
        client = get_llm_client()
        response = client.chat.completions.create(
            model=settings.MODEL,
            messages=[
                {"role": "system", "content": "You are a supply chain analyst. You must respond with ONLY valid JSON, no explanatory text before or after. No markdown code fences. Output only the raw JSON object."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1800,
        )
        raw = response.choices[0].message.content or ""
    except Exception as e:
        logger.warning("discover_supply_chain LLM error for %s: %s", t, e)
        return {"center": {"ticker": t, "name": t}, "nodes": [], "edges": [], "error": str(e)}

    parsed = _parse_json(raw)
    if not parsed:
        logger.warning("discover_supply_chain JSON parse failed for %s. raw=%s", t, raw[:200])
        return {"center": {"ticker": t, "name": t}, "nodes": [], "edges": [], "error": "JSON parse failed"}

    # Normalise fields
    center = parsed.get("center") or {"ticker": t, "name": t}
    nodes: List[Dict] = []
    for n in (parsed.get("nodes") or []):
        nticker = str(n.get("ticker") or "").strip().upper()
        if not nticker:
            continue
        nodes.append({
            "ticker": nticker,
            "name": str(n.get("name") or nticker),
            "relation": str(n.get("relation") or "peer").lower(),
            "tier": int(n.get("tier") or 1),
            "direction": int(n.get("direction") or 0),
            "reason": str(n.get("reason") or ""),
        })

    edges: List[Dict] = []
    for e in (parsed.get("edges") or []):
        src = str(e.get("source") or "").strip().upper()
        tgt = str(e.get("target") or "").strip().upper()
        if src and tgt:
            edges.append({"source": src, "target": tgt})

    # Ensure every node has an edge from/to center
    existing_targets = {e["target"] for e in edges} | {e["source"] for e in edges}
    for node in nodes:
        if node["ticker"] not in existing_targets:
            if node["relation"] == "upstream":
                edges.append({"source": node["ticker"], "target": t})
            else:
                edges.append({"source": t, "target": node["ticker"]})

    return {
        "center": center,
        "nodes": nodes,
        "edges": edges,
        "error": None,
    }
