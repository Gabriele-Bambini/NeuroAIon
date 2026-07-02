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
    # Citation exports from subscription databases (Scopus, Web of Science, Ovid,
    # EBSCO, …) that the reviewer downloaded from their own authenticated session —
    # the legitimate way to use institutional access. RIS/BibTeX/NBIB/EndNote/CSV.
    import_files: list[str] = Field(default_factory=list)
    # Recall amplifiers (all credential-free).
    deep_pagination: bool = False      # fetch beyond the first page, up to the cap
    snowball: bool = False             # backward (references) + forward (cited-by) chasing
    snowball_max: int = 200            # cap on records added by snowballing
    # Folder of full-text PDFs the reviewer already downloaded (via their own
    # legitimate access). Professionally extracted (text + tables + references +
    # statistics) and used as the working full text for screening / extraction.
    fulltext_dir: str = ""


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
    authors: list[str] = Field(default_factory=list)
    affiliation: str = ""
    authors_contact: str = ""
    prospero_export: bool = True
    citation_style: str = "vancouver"

    def byline(self) -> str:
        """Author line for the manuscript (falls back to the contact email)."""
        names = ", ".join(self.authors) if self.authors else (self.authors_contact or "")
        return names

    def byline_full(self) -> str:
        parts = []
        if self.authors:
            parts.append(", ".join(self.authors))
        if self.affiliation:
            parts.append(self.affiliation)
        if self.authors_contact:
            parts.append(self.authors_contact)
        return " · ".join(parts)

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
    pmid: str = ""
    title: str = ""
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    journal: str = ""
    journal_abbrev: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    entry_type: str = "article"          # article | preprint | inproceedings | book | misc
    url: str = ""
    # Every unique identifier we can capture, keyed by scheme: doi | pmid | pmcid |
    # arxiv | openalex | s2 | isbn | nct | mag | dblp. Populated per source and
    # unioned across sources during de-duplication so nothing is ever lost.
    ids: dict[str, str] = Field(default_factory=dict)
    found_by: list[str] = Field(default_factory=list)   # every source that returned it
    retrieval_date: str = ""
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    def all_ids(self) -> dict[str, str]:
        """Normalised {scheme: value} across the dedicated fields and ``ids``."""
        out = {k: str(v).strip() for k, v in (self.ids or {}).items() if v}
        if self.doi:
            out.setdefault("doi", self.doi.lower().strip().replace("https://doi.org/", ""))
        if self.pmid:
            out.setdefault("pmid", str(self.pmid).strip())
        return {k: v for k, v in out.items() if v}

    def id_keys(self) -> set[str]:
        """Canonical ``scheme:value`` keys used for identifier-based de-duplication."""
        return {f"{k}:{v.lower()}" for k, v in self.all_ids().items()}

    def has_resolvable_id(self) -> bool:
        """True if this record can be cited to a verifiable locator."""
        return bool(self.all_ids() or self.url)

    @property
    def uid(self) -> str:
        """A stable identifier: DOI, else PMID, else another id, else title hash."""
        ids = self.all_ids()
        for scheme in ("doi", "pmid", "pmcid", "arxiv", "openalex", "s2"):
            if ids.get(scheme):
                return f"{scheme}:{ids[scheme].lower()}"
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
    """One quantitative result, normalised for meta-analysis.

    Whenever the study reports arm-level raw data (a 2×2 table, or means with
    SDs/medians), the extractor records it in the ``raw_*`` fields below. The
    effect and its standard error are then **recomputed from the raw data** by
    :mod:`neuroaion.extraction_math` rather than trusting the paper's — or an
    LLM's — arithmetic. ``estimate``/``ci``/``se`` are only kept verbatim when
    no raw data is available.
    """
    outcome: str = ""
    measure: str = "SMD"        # SMD | MD | OR | RR | HR | COR | PROP
    estimate: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    se: Optional[float] = None
    n_intervention: Optional[int] = None
    n_comparator: Optional[int] = None
    subgroup: Optional[str] = None       # subgroup label (for subgroup analysis)
    moderator: Optional[float] = None    # covariate for meta-regression

    # --- Raw arm-level data (binary 2×2) --------------------------------
    events_intervention: Optional[int] = None   # a = events in intervention arm
    events_comparator: Optional[int] = None      # c = events in comparator arm

    # --- Raw arm-level data (continuous) --------------------------------
    mean_intervention: Optional[float] = None
    sd_intervention: Optional[float] = None
    mean_comparator: Optional[float] = None
    sd_comparator: Optional[float] = None

    # --- Continuous summaries reported as medians (Wan/Luo/Hozo inputs) --
    median_intervention: Optional[float] = None
    q1_intervention: Optional[float] = None
    q3_intervention: Optional[float] = None
    min_intervention: Optional[float] = None
    max_intervention: Optional[float] = None
    median_comparator: Optional[float] = None
    q1_comparator: Optional[float] = None
    q3_comparator: Optional[float] = None
    min_comparator: Optional[float] = None
    max_comparator: Optional[float] = None

    # --- Dispersion reported indirectly (recover an SD from these) -------
    p_value: Optional[float] = None      # two-sided p for the group difference
    provenance: str = ""                 # how estimate/se were obtained
    recomputed: bool = False             # True once derived from raw data


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
    # Benchmark / gold-standard comparison (methodological reviews).
    gold_standard: str = ""      # reference network(s), e.g. "DREAM5; TRRUST; ChIP-seq"
    datasets: list[str] = Field(default_factory=list)
    baselines: list[str] = Field(default_factory=list)
    funding: str = ""
    notes: str = ""


class RoBDomain(BaseModel):
    name: str
    judgement: str = "some concerns"   # low | some concerns | high
    rationale: str = ""
    support_for_judgement: str = ""    # Cochrane "support for judgement" quote
    signalling_answers: dict[str, str] = Field(default_factory=dict)


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
    outcome: str = ""
    # Estimator / inference provenance.
    tau2_method: str = "DL"             # DL | REML
    knha: bool = False                  # Hartung-Knapp-Sidik-Jonkman applied
    se_pooled: Optional[float] = None
    test_stat: Optional[float] = None
    test_dist: str = "z"                # z | t
    df: Optional[int] = None
    # Heterogeneity detail.
    tau: Optional[float] = None
    H: Optional[float] = None
    q_p_value: Optional[float] = None
    i_squared_ci_lower: Optional[float] = None
    i_squared_ci_upper: Optional[float] = None
    # 95% prediction interval (Higgins-Thompson-Spiegelhalter).
    pi_lower: Optional[float] = None
    pi_upper: Optional[float] = None
    # Subgroup / meta-regression.
    subgroups: list[dict[str, Any]] = Field(default_factory=list)
    q_between: Optional[float] = None
    q_between_df: Optional[int] = None
    q_between_p: Optional[float] = None
    metareg: Optional[dict[str, Any]] = None
    # Sensitivity analyses.
    leave_one_out: list[dict[str, Any]] = Field(default_factory=list)
    cumulative: list[dict[str, Any]] = Field(default_factory=list)
    # Publication-bias assessment (PRISMA item 14).
    eggers_intercept: Optional[float] = None
    eggers_p: Optional[float] = None
    eggers_k: Optional[int] = None
    begg_tau: Optional[float] = None
    begg_p: Optional[float] = None
    trimfill_missing: Optional[int] = None
    trimfill_side: Optional[str] = None
    trimfill_adjusted_estimate: Optional[float] = None
    funnel: list[dict[str, Any]] = Field(default_factory=list)   # {estimate, se}
    interpretation: str = ""


class GradeRow(BaseModel):
    """One row of a GRADE Summary-of-Findings table (PRISMA item 22)."""
    outcome: str = ""
    n_studies: int = 0
    n_participants: Optional[int] = None
    design: str = ""                   # "randomized trials" | "observational studies"
    risk_of_bias: str = "not serious"
    inconsistency: str = "not serious"
    indirectness: str = "not serious"
    imprecision: str = "not serious"
    other: str = "none"                # publication bias etc.
    certainty: str = "moderate"        # high | moderate | low | very low
    effect: str = ""                   # rendered pooled effect + 95% CI
    importance: str = ""               # critical | important | not important


class Synthesis(BaseModel):
    narrative: str = ""
    meta_analysis: Optional[MetaAnalysisResult] = None
    meta_analyses: list[MetaAnalysisResult] = Field(default_factory=list)  # per outcome
    grade_certainty: str = ""          # high | moderate | low | very low
    grade_rationale: str = ""
    grade_table: list[GradeRow] = Field(default_factory=list)              # SoF rows
    limitations: str = ""


# ── PRISMA flow (PRISMA item 16a / Figure 1) ─────────────────────────────────
class PrismaFlow(BaseModel):
    records_identified: dict[str, int] = Field(default_factory=dict)  # per source
    records_total: int = 0
    records_from_databases: int = 0
    records_from_registers: int = 0
    duplicates_removed: int = 0
    auto_excluded: int = 0                  # removed by automation tools before screening
    removed_other_reasons: int = 0
    records_screened: int = 0
    records_excluded_screening: int = 0
    reports_sought: int = 0
    reports_not_retrieved: int = 0
    reports_assessed: int = 0
    reports_excluded: dict[str, int] = Field(default_factory=dict)    # reason → count
    studies_included: int = 0
    reports_of_included: int = 0


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
