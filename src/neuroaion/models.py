"""Pydantic data models shared across the pipeline.

These types are the lingua franca between agents. The whole `ReviewState` is
JSON-serialisable so a run can be persisted after every phase and resumed.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Protocol (PRISMA items 4–7) ──────────────────────────────────────────────
class PICO(BaseModel):
    population: str = ""
    intervention: str = ""
    comparator: str = ""
    outcome: str = ""
    study_designs: list[str] = Field(default_factory=list)
    # Framework-agnostic: any review type (PICO/PECO/SPIDER/PCC/…) via named elements.
    framework: str = "PICO"
    elements: dict[str, str] = Field(default_factory=dict)

    def as_elements(self) -> dict[str, str]:
        """Return the ordered framework elements as label → value."""
        if self.elements:
            return {k: v for k, v in self.elements.items()}
        # Fall back to the classic PICO/PECO slots.
        verb = "Exposure" if self.framework.upper().startswith("PEC") else "Intervention"
        out = {"Population": self.population, verb: self.intervention,
               "Comparator": self.comparator, "Outcome": self.outcome}
        return {k: v for k, v in out.items() if v}


class SearchConfig(BaseModel):
    sources: list[str] = Field(default_factory=lambda: ["pubmed", "europepmc"])
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    languages: list[str] = Field(default_factory=lambda: ["en"])
    max_records_per_source: int = 200
    keywords: list[list[str]] = Field(default_factory=list)


class SynthesisConfig(BaseModel):
    effect_measure: str = "SMD"
    model: str = "random"
    min_studies_for_meta: int = 2
    publication_bias: bool = True   # Egger's test + funnel plot (PRISMA item 14)


class RoBConfig(BaseModel):
    tool: str = "RoB2"
    grade: bool = True


class ReviewProtocol(BaseModel):
    title: str = ""
    question: str = ""
    pico: PICO = Field(default_factory=PICO)
    inclusion_criteria: list[str] = Field(default_factory=list)
    exclusion_criteria: list[str] = Field(default_factory=list)
    search: SearchConfig = Field(default_factory=SearchConfig)
    synthesis: SynthesisConfig = Field(default_factory=SynthesisConfig)
    risk_of_bias: RoBConfig = Field(default_factory=RoBConfig)
    registration: str = "Not registered"
    authors_contact: str = ""
    prospero_export: bool = True
    citation_style: str = "vancouver"

    def criteria_block(self) -> str:
        """A compact, cache-friendly rendering of the eligibility contract."""
        inc = "\n".join(f"  - {c}" for c in self.inclusion_criteria) or "  - (none specified)"
        exc = "\n".join(f"  - {c}" for c in self.exclusion_criteria) or "  - (none specified)"
        elems = "\n".join(f"{k.upper()}: {v}" for k, v in self.pico.as_elements().items())
        return (
            f"TITLE: {self.title}\n"
            f"QUESTION: {self.question}\n"
            f"FRAMEWORK: {self.pico.framework}\n"
            f"{elems}\n"
            f"ELIGIBLE DESIGNS: {', '.join(self.pico.study_designs) or 'any'}\n"
            f"INCLUSION CRITERIA:\n{inc}\n"
            f"EXCLUSION CRITERIA:\n{exc}"
        )


# ── Search strategy (PRISMA item 7) ──────────────────────────────────────────
class DatabaseQuery(BaseModel):
    source: str
    query: str
    rationale: str = ""


class SearchStrategy(BaseModel):
    queries: list[DatabaseQuery] = Field(default_factory=list)
    notes: str = ""


# ── Records (PRISMA items 8, 16) ─────────────────────────────────────────────
class Record(BaseModel):
    """A single bibliographic record retrieved from a source."""
    source: str
    source_id: str = ""
    doi: str = ""
    title: str = ""
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    journal: str = ""
    url: str = ""
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @property
    def uid(self) -> str:
        """A stable identifier for the record (DOI if present, else title hash)."""
        if self.doi:
            return f"doi:{self.doi.lower().strip()}"
        basis = (self.title or self.source_id or "").lower().strip()
        return "sha:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

    def citation(self) -> str:
        first = self.authors[0] if self.authors else "Anon"
        etal = " et al." if len(self.authors) > 1 else ""
        yr = self.year or "n.d."
        return f"{first}{etal} ({yr}). {self.title}. {self.journal}".strip()


class Decision(str, Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    MAYBE = "maybe"


class ScreeningDecision(BaseModel):
    uid: str
    reviewer: str               # e.g. "reviewer_1", "reviewer_2", "adjudicator"
    decision: Decision
    reason: str = ""
    confidence: float = 0.5     # 0–1
    matched_criteria: list[str] = Field(default_factory=list)


class EligibilityDecision(BaseModel):
    uid: str
    eligible: bool
    exclusion_reason: str = ""  # required when eligible is False (PRISMA item 16b)
    full_text_retrieved: bool = False
    notes: str = ""


# ── Extraction & appraisal (PRISMA items 9–12) ───────────────────────────────
class EffectEstimate(BaseModel):
    """One quantitative result, normalised for meta-analysis."""
    outcome: str = ""
    measure: str = "SMD"        # SMD | MD | OR | RR | HR
    estimate: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    se: Optional[float] = None
    n_intervention: Optional[int] = None
    n_comparator: Optional[int] = None


class ExtractionRecord(BaseModel):
    uid: str
    study_label: str = ""        # e.g. "Smith 2021"
    design: str = ""
    population: str = ""
    intervention: str = ""
    comparator: str = ""
    sample_size: Optional[int] = None
    outcomes: list[str] = Field(default_factory=list)
    effects: list[EffectEstimate] = Field(default_factory=list)
    funding: str = ""
    notes: str = ""


class RoBDomain(BaseModel):
    name: str
    judgement: str = "some concerns"   # low | some concerns | high
    rationale: str = ""


class RoBAssessment(BaseModel):
    uid: str
    study_label: str = ""
    tool: str = "RoB2"
    domains: list[RoBDomain] = Field(default_factory=list)
    overall: str = "some concerns"     # low | some concerns | high
    rationale: str = ""


# ── Synthesis (PRISMA item 13) ───────────────────────────────────────────────
class MetaAnalysisResult(BaseModel):
    measure: str = "SMD"
    model: str = "random"
    k_studies: int = 0
    pooled_estimate: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    p_value: Optional[float] = None
    i_squared: Optional[float] = None
    tau_squared: Optional[float] = None
    q_statistic: Optional[float] = None
    forest: list[dict[str, Any]] = Field(default_factory=list)   # per-study rows
    # Publication-bias assessment (PRISMA item 14).
    eggers_intercept: Optional[float] = None
    eggers_p: Optional[float] = None
    eggers_k: Optional[int] = None
    funnel: list[dict[str, Any]] = Field(default_factory=list)   # {estimate, se}
    interpretation: str = ""


class Synthesis(BaseModel):
    narrative: str = ""
    meta_analysis: Optional[MetaAnalysisResult] = None
    grade_certainty: str = ""          # high | moderate | low | very low
    grade_rationale: str = ""
    limitations: str = ""


# ── PRISMA flow (PRISMA item 16a / Figure 1) ─────────────────────────────────
class PrismaFlow(BaseModel):
    records_identified: dict[str, int] = Field(default_factory=dict)  # per source
    records_total: int = 0
    duplicates_removed: int = 0
    records_screened: int = 0
    records_excluded_screening: int = 0
    reports_sought: int = 0
    reports_not_retrieved: int = 0
    reports_assessed: int = 0
    reports_excluded: dict[str, int] = Field(default_factory=dict)    # reason → count
    studies_included: int = 0


# ── The whole run ────────────────────────────────────────────────────────────
class ReviewState(BaseModel):
    run_id: str
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    mock: bool = False
    model: str = ""
    protocol: ReviewProtocol = Field(default_factory=ReviewProtocol)
    strategy: SearchStrategy = Field(default_factory=SearchStrategy)
    records: list[Record] = Field(default_factory=list)
    unique_records: list[Record] = Field(default_factory=list)
    screening: list[ScreeningDecision] = Field(default_factory=list)
    cohen_kappa: Optional[float] = None
    included_after_screening: list[str] = Field(default_factory=list)
    eligibility: list[EligibilityDecision] = Field(default_factory=list)
    included_studies: list[str] = Field(default_factory=list)
    extractions: list[ExtractionRecord] = Field(default_factory=list)
    rob: list[RoBAssessment] = Field(default_factory=list)
    synthesis: Synthesis = Field(default_factory=Synthesis)
    prisma: PrismaFlow = Field(default_factory=PrismaFlow)
    log: list[str] = Field(default_factory=list)
