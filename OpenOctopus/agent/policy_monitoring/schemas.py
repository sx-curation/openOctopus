"""
Unified schema for policy/regulatory events.
All adapters normalize to PolicyEvent before returning.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, field_validator


class PolicyEvent(BaseModel):
    """A single policy/regulatory event from any supported source."""

    id: str  # stable 16-char hex hash: sha256(source:doc_id:published_at)
    source: Literal["EUR_LEX", "FEDERAL_REGISTER", "SEC"]
    source_doc_id: str  # CELEX / document_number / CIK+accession or rule id
    title: str
    published_at: datetime
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    jurisdictions: List[str]  # e.g. ["EU"] or ["US"]
    regulator: Optional[str] = None  # EC / EBA / SEC / CFTC …
    topics: List[str] = []
    url: str  # canonical human-readable URL
    summary: str  # 1–3 sentences
    fulltext_url: Optional[str] = None  # direct link to full document
    relationships: Dict[str, List[str]] = {}  # amends/repeals/amended_by …
    sentiment_or_tone: Optional[float] = None  # reserved; MVP leaves None
    raw_ref: Optional[str] = None  # path to raw JSON cache file if stored

    @field_validator("title", "summary", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @field_validator("url", mode="before")
    @classmethod
    def ensure_https(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def make_id(cls, source: str, source_doc_id: str, published_at: datetime) -> str:
        """Deterministic 16-char ID — same inputs always produce the same hash."""
        key = f"{source}:{source_doc_id}:{published_at.isoformat()}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class ImpactClassification(BaseModel):
    """Result of classify_impact()."""

    event_id: str
    impact: Literal["opportunity", "constraint", "neutral"]
    rationale: str
    opportunity_signals: List[str] = []
    constraint_signals: List[str] = []


class DiffSummary(BaseModel):
    """Result of compare_versions()."""

    source: str
    source_doc_id: str
    old_version: Optional[dict] = None  # metadata snapshot
    new_version: Optional[dict] = None
    changed_fields: List[str] = []
    title_changed: bool = False
    summary_changed: bool = False
    note: str = ""
