import re

import yfinance as yf

from config.ui_data_contracts import get_ui_section_contract
from data_sources.market.service import get_market_analyst_snapshot, get_market_quote
from services.dashboard.commitment_analysis import build_commitment_context
from tools.analyst_estimates import get_analyst_estimates
from tools.financials import get_key_financials


def _get_company_name(ticker: str) -> str:
    """Return company long name for a ticker, falling back to the ticker symbol."""
    try:
        info = yf.Ticker(ticker).fast_info
        return getattr(info, 'company_name', None) or getattr(info, 'longName', None) or ticker
    except Exception:
        pass
    try:
        info = yf.Ticker(ticker).info
        return info.get('longName') or info.get('shortName') or ticker
    except Exception:
        return ticker

_GUIDANCE_HINTS = ("will", "expect", "plan", "target", "guidance", "committed", "continue", "outlook", "remain",
                   "forecast", "anticipate", "project", "estimate", "intend", "believe", "drive", "deliver")

# ── Alpha Signals (超额收益机会) ──
_ALPHA_THEMES = {
    "product_mix_upgrade": {
        "label": "Product Mix Upgrade",
        "desc": {
            "en": "Higher-margin product mix → structural gross margin improvement",
            "zh": "高利润产品占比提升，毛利率结构性改善",
            "de": "Höhermargiger Produktmix → strukturelle Bruttomarge-Verbesserung",
        },
        "keywords": {"premium", "premiumization", "high-margin", "mix", "upgrade", "upsell", "attach"},
    },
    "operating_leverage": {
        "label": "Operating Leverage",
        "desc": {
            "en": "Revenue growing faster than costs; +10% rev can mean +30% profit",
            "zh": "收入增速快于成本，营收+10%净利可+30%",
            "de": "Umsatz wächst schneller als Kosten; +10% Umsatz → +30% Gewinn",
        },
        "keywords": {"scalability", "scale", "leverage", "discipline", "disciplined", "absorption", "efficiency",
                     "efficient", "cost", "margin", "margins", "profitability", "profitable", "operating"},
    },
    "new_growth_pillars": {
        "label": "New Growth Pillars",
        "desc": {
            "en": "Gaining entry to new markets; expanding market share",
            "zh": "新领域拿到入场券，市占率扩展",
            "de": "Eintritt in neue Märkte; Marktanteil wächst",
        },
        "keywords": {"share", "wins", "ramp", "introduction", "launch", "launched", "pipeline", "innovation",
                     "innovative", "breakthrough", "transformative", "opportunity", "opportunities", "growth",
                     "grow", "growing", "expand", "expansion", "accelerate", "acceleration", "momentum"},
    },
    "capital_return": {
        "label": "Capital Return",
        "desc": {
            "en": "Abundant cash flow; management sees stock as undervalued",
            "zh": "现金流充裕，管理层认为股价被低估",
            "de": "Starker Cashflow; Management hält Aktie für unterbewertet",
        },
        "keywords": {"buyback", "repurchase", "dividend", "dividends", "payout", "fcf", "cashflow",
                     "cash", "yield", "return", "returns", "shareholder", "shareholders"},
    },
}

# ── Beta Risks (系统性/公司特定风险) ──
_BETA_THEMES = {
    "inventory_destocking": {
        "label": "Inventory Destocking",
        "desc": {
            "en": "Destocking cycle; next 1-2 quarters under pressure",
            "zh": "去库存周期，未来1-2季业绩承压",
            "de": "Lagerabbau-Zyklus; nächste 1-2 Quartale unter Druck",
        },
        "keywords": {"inventory", "inventories", "destocking", "correction", "channel", "write-down",
                     "writedown", "excess", "backlog", "overstock"},
    },
    "asp_erosion": {
        "label": "ASP Erosion",
        "desc": {
            "en": "Price war or declining competitiveness; sacrificing margin for share",
            "zh": "价格战或竞争力下降，牺牲利润保份额",
            "de": "Preiskampf oder sinkende Wettbewerbsfähigkeit; Marge geopfert",
        },
        "keywords": {"pricing", "price", "concession", "concessions", "negotiation", "competitive",
                     "competition", "erosion", "discount", "discounting", "pressure", "pressured"},
    },
    "macro_scapegoating": {
        "label": "Macro Scapegoating",
        "desc": {
            "en": "Frequent blame on environment = lack of execution; red flag",
            "zh": "频繁怪罪环境=缺乏执行力，红旗信号",
            "de": "Häufige Schuldzuweisung ans Umfeld = mangelnde Umsetzung; Warnsignal",
        },
        "keywords": {"macro", "geopolitical", "uncertainty", "headwind", "headwinds", "forex", "fx",
                     "volatility", "tariff", "tariffs", "recession", "slowdown", "downturn",
                     "challenging", "difficult", "adverse"},
    },
    "capex_anomaly": {
        "label": "CapEx Anomaly",
        "desc": {
            "en": "CapEx cuts signal pessimism about future demand",
            "zh": "削减资本支出=对未来需求悲观",
            "de": "Investitionskürzungen signalisieren Pessimismus bei der Nachfrage",
        },
        "keywords": {"capex", "reduction", "delay", "delays", "delayed", "defer", "deferred",
                     "underutilization", "utilization", "cutback", "suspension", "paused"},
    },
}

# ── Disguised Negatives (伪正向信号) ──
# Phrases that sound positive but carry hidden negative implications
_DISGUISED_NEGATIVE_PATTERNS = {
    "internal_efficiency_pivot": {
        "label": "Internal Efficiency Pivot",
        "desc": {
            "en": "Focused on efficiency = external growth has stalled; cost-cutting only",
            "zh": "专注内部效率 = 外部增长停滞，只能靠裁员节流",
            "de": "Fokus auf Effizienz = externes Wachstum stagniert; nur Kostensenkung",
        },
        "translation": {
            "en": "External growth has stalled; resorting to cost-cutting.",
            "zh": "外部增长已经停滞，只能靠裁员省钱。",
            "de": "Externes Wachstum stagniert; nur noch Kostensenkung.",
        },
        "patterns": [
            r"focus(?:ed|ing)?\s+on\s+(?:internal\s+)?(?:efficiency|optimization|streamlining)",
            r"(?:operational|cost)\s+(?:efficiency|optimization|improvement)\s+(?:initiative|program|effort)",
            r"right[\s-]?sizing",
            r"doing\s+more\s+with\s+less",
            r"lean(?:er)?\s+(?:organization|structure|operations)",
        ],
    },
    "strategic_inventory_mgmt": {
        "label": "Strategic Inventory Management",
        "desc": {
            "en": "Customer 'strategic inventory management' = they stopped ordering",
            "zh": "客户战略性库存管理 = 客户不再下单了",
            "de": "Kunden-'strategisches Bestandsmanagement' = Bestellstopp",
        },
        "translation": {
            "en": "Customers have stopped ordering.",
            "zh": "客户不再向我们下单了。",
            "de": "Kunden haben aufgehört zu bestellen.",
        },
        "patterns": [
            r"(?:customer|client)s?\s+(?:are\s+)?(?:strategically|carefully|prudently)\s+(?:managing|adjusting|optimizing)\s+(?:inventory|inventories|stock)",
            r"strategic\s+inventory\s+(?:management|positioning|adjustment)",
            r"customer\s+(?:inventory\s+)?(?:digestion|normalization|rationalization)",
            r"(?:cautious|conservative)\s+(?:ordering|purchasing|procurement)\s+(?:pattern|behavior|environment)",
        ],
    },
    "investment_year_framing": {
        "label": "Investment Year Framing",
        "desc": {
            "en": "'Investment year' framing = profits will look ugly",
            "zh": "投资机遇之年 = 今年利润会很难看",
            "de": "'Investitionsjahr'-Framing = Gewinne werden schlecht aussehen",
        },
        "translation": {
            "en": "Profits will look ugly because we're spending heavily.",
            "zh": "今年的利润会非常难看（因为钱都花掉了）。",
            "de": "Die Gewinne werden schlecht ausfallen, weil stark investiert wird.",
        },
        "patterns": [
            r"(?:this\s+is\s+)?(?:a|an)\s+(?:investment|transition|transformation|building|foundational)\s+year",
            r"investing\s+(?:heavily|significantly|aggressively)\s+(?:for|in)\s+(?:the\s+)?(?:future|long[\s-]?term|growth)",
            r"(?:near[\s-]?term|short[\s-]?term)\s+(?:margin|profit|earnings)\s+(?:pressure|headwind|trade[\s-]?off|sacrifice)",
            r"(?:front[\s-]?load(?:ed|ing)?|accelerat(?:ed|ing))\s+(?:investment|spending|capex)",
        ],
    },
    "undervaluation_plea": {
        "label": "Undervaluation Plea",
        "desc": {
            "en": "'Valuation doesn\\'t reflect value' = stock crashed, no real fix",
            "zh": "估值未反映真实价值 = 股价跌惨了，除了喊话也没别招",
            "de": "'Bewertung spiegelt nicht den Wert wider' = Aktie abgestürzt",
        },
        "translation": {
            "en": "Stock has crashed; management can only talk it up.",
            "zh": "股价跌惨了，但我除了喊话也没别招。",
            "de": "Aktie abgestürzt; Management kann nur reden.",
        },
        "patterns": [
            r"(?:current\s+)?(?:valuation|share\s+price|stock\s+price)\s+(?:does\s+not|doesn'?t|has\s+not|hasn'?t)\s+(?:reflect|capture|represent)",
            r"(?:intrinsic|true|underlying|real)\s+value\s+(?:is\s+)?(?:not\s+)?(?:reflected|recognized|appreciated)",
            r"(?:significantly|substantially|meaningfully)\s+undervalued",
            r"disconnect\s+between\s+(?:fundamentals|performance)\s+and\s+(?:valuation|stock|share\s+price|market)",
        ],
    },
    "selective_metric_shift": {
        "label": "Selective Metric Shift",
        "desc": {
            "en": "Switching to flattering metrics = core metrics deteriorating",
            "zh": "换指标报喜 = 核心指标恶化，换一个好看的讲",
            "de": "Wechsel zu schmeichelhaften Kennzahlen = Kernkennzahlen verschlechtern sich",
        },
        "translation": {
            "en": "Core metrics are deteriorating; pivoting to flattering alternatives.",
            "zh": "核心指标恶化，换一个好看的讲。",
            "de": "Kernkennzahlen verschlechtern sich; Wechsel zu schmeichelhaften Alternativen.",
        },
        "patterns": [
            r"(?:if\s+you\s+)?(?:exclude|excluding|adjust(?:ed|ing)?\s+for|stripping\s+out|normaliz(?:ed|ing))\s+(?:one[\s-]?time|non[\s-]?recurring|restructuring|impairment)",
            r"on\s+an?\s+(?:adjusted|non[\s-]?gaap|organic|constant[\s-]?currency|underlying)\s+basis",
            r"(?:core|underlying|adjusted)\s+(?:earnings|revenue|growth)\s+(?:grew|increased|improved)",
        ],
    },
}

_POSITIVE_TERMS = set()
for theme in _ALPHA_THEMES.values():
    _POSITIVE_TERMS |= theme["keywords"]
_NEGATIVE_TERMS = set()
for theme in _BETA_THEMES.values():
    _NEGATIVE_TERMS |= theme["keywords"]

_WORD_CLOUD_STOPWORDS = {
    "about", "after", "again", "analyst", "because", "business", "company", "could", "during",
    "first", "forward", "management", "quarter", "there", "these", "those", "their", "which", "while",
}


def build_dashboard_summary(ticker: str) -> dict:
    ticker = ticker.upper()
    trinity_contract = get_ui_section_contract("dashboard.trinity_hero") or {"fields": []}
    macro_contract = get_ui_section_contract("dashboard.macro_context") or {"fields": []}

    trinity_fields = {field["name"]: field for field in trinity_contract["fields"]}
    macro_fields = {field["name"]: field for field in macro_contract["fields"]}
    ticker_snapshot = get_market_quote(ticker)
    analyst_snapshot = get_market_analyst_snapshot(ticker)
    estimates = get_analyst_estimates(ticker)
    key_financials = get_key_financials(ticker)
    commitment_context = build_commitment_context(ticker, estimates)
    realized_field = _build_realized_performance_field(trinity_fields, estimates)
    guidance_field = _build_guidance_field(trinity_fields, estimates)
    consensus_field = _build_consensus_field(trinity_fields, analyst_snapshot)
    divergence_field = _build_divergence_field(
        trinity_fields,
        guidance_field,
        consensus_field,
        analyst_snapshot,
    )
    trend_field = _build_alignment_trend_field(
        trinity_fields,
        ticker,
        commitment_context,
    )

    return {
        "ticker": ticker,
        "company_name": _get_company_name(ticker),
        "ticker_snapshot": ticker_snapshot,
        "analyst_snapshot": analyst_snapshot if "error" not in analyst_snapshot else None,
        "key_financials": None if "error" in key_financials else key_financials,
        "trinity": {
            "realized_performance_score": realized_field,
            "guidance_vs_actuals_score": guidance_field,
            "analyst_consensus_score": consensus_field,
            "divergence_score": divergence_field,
            "alignment_trend_series": trend_field,
        },
        "raw_data": _build_trinity_raw_data(ticker_snapshot, analyst_snapshot, key_financials, estimates),
        "trinity_source_meta": _build_trinity_source_meta(
            ticker_snapshot,
            analyst_snapshot,
            realized_field,
            guidance_field,
            consensus_field,
            trend_field,
        ),
        "macro_context": {
            "theme_title": {
                "status": macro_fields.get("theme_title", {}).get("status", "planned"),
                "value": "Commercial Real Estate",
                "rationale": macro_fields.get("theme_title", {}).get("rationale"),
            },
            "numeric_macro_claims": _no_available_data_field(macro_fields, "numeric_macro_claims"),
        },
    }


def _no_available_data_field(fields: dict, field_name: str) -> dict:
    field = fields.get(field_name, {})
    return {
        "status": "no_available_data",
        "label": "NO AVAILABLE DATA",
        "value": None,
        "rationale": field.get("rationale"),
    }


def _interim_solution_field(fields: dict, field_name: str, value, rationale: str, detail: dict | None = None) -> dict:
    field = fields.get(field_name, {})
    return {
        "status": "interim_solution",
        "label": "interim solution",
        "value": value,
        "rationale": rationale or field.get("rationale"),
        "detail": detail or {},
    }


def _build_realized_performance_field(fields: dict, estimates: dict) -> dict:
    quarters = sorted(
        [item for item in estimates.get("quarters", []) if item.get("date")],
        key=lambda item: item["date"],
        reverse=True,
    )
    if len(quarters) < 5:
        return _no_available_data_field(fields, "realized_performance_score")

    current = quarters[0]
    prior_year = quarters[4]
    current_eps = current.get("eps_actual")
    prior_eps = prior_year.get("eps_actual")
    if current_eps is None or prior_eps in (None, 0):
        return _no_available_data_field(fields, "realized_performance_score")

    yoy_pct = ((current_eps - prior_eps) / abs(prior_eps)) * 100
    bounded_yoy_pct = max(-100.0, min(100.0, yoy_pct))
    score = round(50 + bounded_yoy_pct * 0.5)
    return _interim_solution_field(
        fields,
        "realized_performance_score",
        score,
        (
            "interim solution — using latest reported EPS year-over-year growth, mapped "
            "onto a 0-100 scale, as a proxy for realized performance until portfolio data is available."
        ),
        {
            "current_quarter_date": current.get("date"),
            "current_eps_actual": current_eps,
            "prior_year_quarter_date": prior_year.get("date"),
            "prior_year_eps_actual": prior_eps,
            "eps_yoy_pct": round(yoy_pct, 2),
            "source": "yahoo_earnings_dates",
            "source_generated_at": current.get("date"),
        },
    )


def _build_guidance_field(fields: dict, estimates: dict) -> dict:
    quarters = estimates.get("quarters", [])
    eps_surprises = [abs(item["eps_surprise_pct"]) for item in quarters if item.get("eps_surprise_pct") is not None]
    revenue_surprises = [
        abs(item["revenue_surprise_pct"])
        for item in quarters
        if item.get("revenue_surprise_pct") is not None
    ]
    if not eps_surprises and not revenue_surprises:
        return _no_available_data_field(fields, "guidance_vs_actuals_score")

    avg_eps_abs = sum(eps_surprises) / len(eps_surprises) if eps_surprises else 0
    avg_rev_abs = sum(revenue_surprises) / len(revenue_surprises) if revenue_surprises else 0
    score = max(0, min(100, round(100 - avg_eps_abs * 4 - avg_rev_abs * 1.5)))
    return _interim_solution_field(
        fields,
        "guidance_vs_actuals_score",
        score,
        (
            "interim solution — using trailing EPS/revenue surprise consistency "
            "as a proxy for guidance quality until a structured guidance source is added."
        ),
        {
            "avg_abs_eps_surprise_pct": round(avg_eps_abs, 2),
            "avg_abs_revenue_surprise_pct": round(avg_rev_abs, 2) if revenue_surprises else None,
            "quarters_used": len(quarters),
            "source": "earnings_cycle_service",
            "source_generated_at": _latest_quarter_date(quarters),
        },
    )


def _build_consensus_field(fields: dict, analyst_snapshot: dict) -> dict:
    if "error" in analyst_snapshot or not analyst_snapshot.get("current_recommendation"):
        return _no_available_data_field(fields, "analyst_consensus_score")

    summary = analyst_snapshot["current_recommendation"]
    return _interim_solution_field(
        fields,
        "analyst_consensus_score",
        summary.get("score"),
        (
            "interim solution — using Yahoo recommendation trend counts as a proxy "
            "for analyst consensus until a dedicated consensus feed is added."
        ),
        {
            "period": summary.get("period"),
            "strong_buy": summary.get("strong_buy"),
            "buy": summary.get("buy"),
            "hold": summary.get("hold"),
            "sell": summary.get("sell"),
            "strong_sell": summary.get("strong_sell"),
            "target_upside_pct": analyst_snapshot.get("target_upside_pct"),
            "source": analyst_snapshot.get("source"),
            "source_generated_at": analyst_snapshot.get("fetched_at") or summary.get("period"),
        },
    )


def _build_divergence_field(
    fields: dict,
    guidance_field: dict,
    consensus_field: dict,
    analyst_snapshot: dict,
) -> dict:
    if guidance_field["status"] != "interim_solution" or consensus_field["status"] != "interim_solution":
        return _no_available_data_field(fields, "divergence_score")

    target_upside = analyst_snapshot.get("target_upside_pct")
    target_component = min(20, abs(target_upside or 0) / 2)
    score = max(
        0,
        min(
            100,
            round(abs(guidance_field["value"] - consensus_field["value"]) * 0.9 + target_component),
        ),
    )
    return _interim_solution_field(
        fields,
        "divergence_score",
        score,
        (
            "interim solution — combining surprise-consistency and recommendation-trend "
            "proxies to approximate divergence until a full holdings and analyst model is available."
        ),
        {
            "guidance_proxy_score": guidance_field["value"],
            "consensus_proxy_score": consensus_field["value"],
            "target_upside_pct": target_upside,
            "source": "dashboard_summary_derived",
            "source_generated_at": (
                guidance_field.get("detail", {}).get("source_generated_at")
                or consensus_field.get("detail", {}).get("source_generated_at")
            ),
        },
    )


def _build_alignment_trend_field(
    fields: dict,
    ticker: str,
    commitment_context: dict,
) -> dict:
    return _build_alignment_word_cloud_field(fields, ticker, commitment_context)


def _build_alignment_word_cloud_field(fields: dict, ticker: str, commitment_context: dict) -> dict:
    llm_analysis = commitment_context.get("llm_commitment_analysis", {})
    current_cached = commitment_context.get("current_cached_transcript") or {}
    current_fallback = commitment_context.get("current_fallback_transcript") or {}
    llm_sentences = _alignment_sentences_from_llm(llm_analysis)
    source_generated_at = current_cached.get("date") or current_fallback.get("transcript_date")

    # Always scan full transcript for Alpha/Beta signal classification
    text = commitment_context.get("current_text")
    transcript_sentences = []
    if text:
        transcript_sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", text)
            if len(sentence.strip()) >= 30
        ]

    # Combine LLM-extracted + transcript sentences (deduplicated)
    all_sentences = llm_sentences[:]
    seen = set(s.lower()[:60] for s in all_sentences)
    for s in transcript_sentences:
        if s.lower()[:60] not in seen:
            all_sentences.append(s)
            seen.add(s.lower()[:60])

    if not all_sentences:
        return _no_available_data_field(fields, "alignment_trend_series")

    source = "llm_commitment_analysis + transcript" if llm_sentences else (
        current_cached.get("source") or "earnings_transcript_fallback"
    )
    rationale = (
        "interim solution — classifying transcript into Alpha signals "
        "and Beta risks based on institutional investment themes."
    )

    positive = _count_sentiment_terms(all_sentences, _POSITIVE_TERMS)
    negative = _count_sentiment_terms(all_sentences, _NEGATIVE_TERMS)
    alpha_signals = _classify_themed_signals(all_sentences, _ALPHA_THEMES)
    beta_risks = _classify_themed_signals(all_sentences, _BETA_THEMES)
    disguised_negatives = _classify_disguised_negatives(all_sentences)
    if not positive and not negative and not alpha_signals and not beta_risks:
        return _no_available_data_field(fields, "alignment_trend_series")

    return _interim_solution_field(
        fields,
        "alignment_trend_series",
        {
            "mode": "alpha_beta_signals",
            "positive_keywords": positive,
            "negative_keywords": negative,
            "alpha_signals": alpha_signals,
            "beta_risks": beta_risks,
            "disguised_negatives": disguised_negatives,
        },
        (
            rationale
        ),
        {
            "render_mode": "alpha_beta_signals",
            "source": source,
            "source_generated_at": source_generated_at,
            "sentence_count": len(all_sentences),
            "llm_available": "error" not in llm_analysis,
        },
    )


def _count_sentiment_terms(sentences: list[str], lexicon: set[str]) -> list[dict]:
    counts: dict[str, int] = {}
    for sentence in sentences:
        for token in re.findall(r"[a-zA-Z]{4,}", sentence.lower()):
            if token in _WORD_CLOUD_STOPWORDS or token not in lexicon:
                continue
            counts[token] = counts.get(token, 0) + 1
    return [
        {"term": term, "count": count}
        for term, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]


def _classify_themed_signals(sentences: list[str], themes: dict) -> list[dict]:
    """Classify sentences into themed signal categories, returning hit counts per theme."""
    results = []
    for theme_id, theme in themes.items():
        keywords = theme["keywords"]
        hit_terms: dict[str, int] = {}
        for sentence in sentences:
            tokens = set(re.findall(r"[a-zA-Z\-]{3,}", sentence.lower()))
            for kw in tokens & keywords:
                hit_terms[kw] = hit_terms.get(kw, 0) + 1
        if hit_terms:
            top_terms = sorted(hit_terms.items(), key=lambda x: -x[1])[:5]
            results.append({
                "theme": theme_id,
                "label": theme["label"],
                "label_key": f"theme.{theme_id}",
                "desc": theme["desc"],
                "total_hits": sum(hit_terms.values()),
                "top_terms": [{"term": t, "count": c} for t, c in top_terms],
            })
    results.sort(key=lambda x: -x["total_hits"])
    return results


def _classify_disguised_negatives(sentences: list[str]) -> list[dict]:
    """Detect statements that sound positive but carry hidden negative implications."""
    results = []
    for theme_id, theme in _DISGUISED_NEGATIVE_PATTERNS.items():
        matched_sentences = []
        for sentence in sentences:
            lower = sentence.lower()
            for pattern in theme["patterns"]:
                if re.search(pattern, lower):
                    matched_sentences.append(sentence.strip()[:120])
                    break
        if matched_sentences:
            results.append({
                "theme": theme_id,
                "label": theme["label"],
                "label_key": f"theme.{theme_id}",
                "desc": theme["desc"],
                "translation": theme["translation"],
                "hit_count": len(matched_sentences),
                "examples": matched_sentences[:3],
            })
    results.sort(key=lambda x: -x["hit_count"])
    return results


def _alignment_sentences_from_llm(llm_analysis: dict) -> list[str]:
    if "error" in llm_analysis:
        return []

    commitment_score = llm_analysis.get("t_minus_1_commitment_score", {})
    mention_score = llm_analysis.get("t_zero_mention_rate", {})
    statements = []
    # New checklist schema: items with topic/comparison_basis/actual_reference
    for item in commitment_score.get("items", []):
        for key in ("topic", "comparison_basis", "actual_reference"):
            val = item.get(key)
            if val and len(val) >= 10:
                statements.append(val)
    # Old schema: hard_commitments / forward_guidance with statement
    for item in commitment_score.get("hard_commitments", []):
        statement = item.get("statement")
        if statement:
            statements.append(statement)
    for item in commitment_score.get("forward_guidance", []):
        statement = item.get("statement")
        if statement:
            statements.append(statement)
    # New schema: matches with topic/deviation_note
    for item in mention_score.get("matches", []):
        for key in ("current_reference", "topic", "deviation_note"):
            val = item.get(key)
            if val and len(val) >= 10:
                statements.append(val)
    return statements


def _latest_quarter_date(quarters: list[dict]) -> str | None:
    dated = [item.get("date") for item in quarters if item.get("date")]
    return max(dated) if dated else None


def _build_trinity_source_meta(
    ticker_snapshot: dict,
    analyst_snapshot: dict,
    realized_field: dict,
    guidance_field: dict,
    consensus_field: dict,
    trend_field: dict,
    ) -> list[dict]:
    return [
        {
            "field": "ticker_snapshot",
            "label": "Ticker",
            "source": ticker_snapshot.get("source", "n/a"),
            "source_generated_at": ticker_snapshot.get("fetched_at"),
        },
        {
            "field": "realized_performance_score",
            "label": "Realized",
            "source": realized_field.get("detail", {}).get("source", "n/a"),
            "source_generated_at": realized_field.get("detail", {}).get("source_generated_at"),
        },
        {
            "field": "guidance_vs_actuals_score",
            "label": "Guidance",
            "source": guidance_field.get("detail", {}).get("source", "n/a"),
            "source_generated_at": guidance_field.get("detail", {}).get("source_generated_at"),
        },
        {
            "field": "analyst_consensus_score",
            "label": "Consensus",
            "source": (
                consensus_field.get("detail", {}).get("source")
                or analyst_snapshot.get("source")
                or "n/a"
            ),
            "source_generated_at": (
                consensus_field.get("detail", {}).get("source_generated_at")
                or analyst_snapshot.get("fetched_at")
            ),
        },
        {
            "field": "alignment_trend_series",
            "label": "Trend",
            "source": trend_field.get("detail", {}).get("source", "n/a"),
            "source_generated_at": trend_field.get("detail", {}).get("source_generated_at"),
        },
    ]


def _build_trinity_raw_data(
    ticker_snapshot: dict,
    analyst_snapshot: dict,
    key_financials: dict,
    estimates: dict,
) -> dict:
    quarters = sorted(
        [item for item in estimates.get("quarters", []) if item.get("date")],
        key=lambda item: item["date"],
        reverse=True,
    )
    latest = quarters[0] if quarters else {}
    eps_surprises = [item.get("eps_surprise_pct") for item in quarters if item.get("eps_surprise_pct") is not None]
    revenue_surprises = [item.get("revenue_surprise_pct") for item in quarters if item.get("revenue_surprise_pct") is not None]
    return {
        "earnings_power": [
            {"label": "TTM EPS", "value": None if "error" in key_financials else key_financials.get("eps_ttm")},
            {"label": "Forward EPS", "value": None if "error" in key_financials else key_financials.get("eps_forward")},
        ],
        "surprise_track": [
            {
                "label": "Trailing EPS Surprise",
                "value": round(sum(eps_surprises) / len(eps_surprises), 2) if eps_surprises else None,
            },
            {
                "label": "Trailing Revenue Surprise",
                "value": round(sum(revenue_surprises) / len(revenue_surprises), 2) if revenue_surprises else None,
            },
        ],
        "market_lens": [
            {"label": "Current Price", "value": ticker_snapshot.get("price")},
            {
                "label": "Analyst Estimate",
                "value": None if "error" in analyst_snapshot else analyst_snapshot.get("price_targets", {}).get("mean"),
            },
            {"label": "Next EPS Estimate", "value": latest.get("eps_estimate")},
        ],
    }
