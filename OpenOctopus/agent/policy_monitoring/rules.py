"""
Keyword-based impact classification rules.
MVP: rule/keyword only — no LLM, no compliance determinations.
Outputs risk/opportunity signals only.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.policy_monitoring.schemas import PolicyEvent, ImpactClassification

# ---------------------------------------------------------------------------
# Keyword lists
# ---------------------------------------------------------------------------

OPPORTUNITY_KEYWORDS: list[str] = [
    "grant", "funding", "incentive", "subsidy", "support program",
    "promote", "facilitate", "encourage", "enable", "sandbox",
    "liberalize", "streamline", "deregulate", "simplify",
    "reduce burden", "tax credit", "tax deduction", "benefit",
    "pilot program", "exemption", "waiver", "safe harbor",
    "innovation", "accelerat",
]

CONSTRAINT_KEYWORDS: list[str] = [
    "ban", "prohibit", "restrict", "limitation", "sanction",
    "penalty", "fine", "civil money penalty", "enforcement",
    "require", "mandate", "comply", "obligation", "must",
    "tariff", "embargo", "export control", "import restriction",
    "investigation", "scrutiny", "antitrust", "cease and desist",
    "suspend", "revoke", "freeze", "block", "delist",
    "capital requirement", "reporting requirement", "stress test",
    "systemic risk", "designation", "order to show cause",
]

# Jurisdiction shortcuts mapped to display labels
JURISDICTION_MAP: dict[str, str] = {
    "EU": "European Union",
    "US": "United States",
    "UK": "United Kingdom",
}

# Regulator name normalisations (raw string → canonical)
REGULATOR_ALIASES: dict[str, str] = {
    "securities and exchange commission": "SEC",
    "sec": "SEC",
    "european commission": "EC",
    "ec": "EC",
    "european central bank": "ECB",
    "ecb": "ECB",
    "european banking authority": "EBA",
    "eba": "EBA",
    "federal reserve": "FED",
    "consumer financial protection bureau": "CFPB",
    "cfpb": "CFPB",
    "commodity futures trading commission": "CFTC",
    "cftc": "CFTC",
    "financial industry regulatory authority": "FINRA",
    "finra": "FINRA",
}


def normalize_regulator(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.lower().strip()
    return REGULATOR_ALIASES.get(key, raw.strip())


# ---------------------------------------------------------------------------
# Topic detection
# ---------------------------------------------------------------------------

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "ai_regulation": ["artificial intelligence", "ai act", "machine learning", "algorithmic"],
    "crypto_digital_assets": ["crypto", "digital asset", "stablecoin", "defi", "blockchain", "cbdc"],
    "esg_climate": ["esg", "climate", "sustainability", "carbon", "green finance", "disclosure"],
    "banking_capital": ["capital requirement", "basel", "cet1", "stress test", "leverage ratio"],
    "sanctions": ["sanction", "ofac", "export control", "embargo", "entity list"],
    "data_privacy": ["gdpr", "privacy", "personal data", "data protection"],
    "market_structure": ["market structure", "best execution", "order routing", "dark pool"],
    "insider_trading": ["insider", "material non-public", "misappropriation"],
    "m_and_a": ["merger", "acquisition", "takeover", "antitrust", "competition"],
    "tax": ["tax", "withholding", "fatca", "crs", "transfer pricing"],
}


def detect_topics(text: str) -> list[str]:
    text_lower = text.lower()
    return [topic for topic, kws in TOPIC_KEYWORDS.items() if any(kw in text_lower for kw in kws)]


# ---------------------------------------------------------------------------
# Impact classifier
# ---------------------------------------------------------------------------

def classify_impact(event: "PolicyEvent") -> "ImpactClassification":
    """
    Rule-based impact classification.
    Returns opportunity | constraint | neutral + rationale.

    NOTE (MVP): This outputs risk/opportunity *signals*, not compliance determinations.
    Do not interpret as legal advice.
    """
    from agent.policy_monitoring.schemas import ImpactClassification

    text = (event.title + " " + event.summary).lower()

    opp_hits = [k for k in OPPORTUNITY_KEYWORDS if k in text]
    con_hits = [k for k in CONSTRAINT_KEYWORDS if k in text]

    opp_score = len(opp_hits)
    con_score = len(con_hits)

    if con_score > opp_score:
        impact = "constraint"
        rationale = (
            f"Constraint signals detected ({con_score}): "
            + ", ".join(f'"{h}"' for h in con_hits[:5])
            + ". No compliance determination implied — signal only."
        )
    elif opp_score > 0:
        impact = "opportunity"
        rationale = (
            f"Opportunity signals detected ({opp_score}): "
            + ", ".join(f'"{h}"' for h in opp_hits[:5])
            + ". No compliance determination implied — signal only."
        )
    else:
        impact = "neutral"
        rationale = "No strong opportunity or constraint signals in title/summary."

    return ImpactClassification(
        event_id=event.id,
        impact=impact,
        rationale=rationale,
        opportunity_signals=opp_hits,
        constraint_signals=con_hits,
    )
