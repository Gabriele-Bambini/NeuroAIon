"""Formal systematic-review documents (the physical dossier).

Produces the standalone documents a rigorous review must hand over, beyond the
manuscript: protocol, search log, screening log, list of excluded full texts
(with reasons), data-extraction form, a per-study risk-of-bias report, and a
GRADE Summary-of-Findings table. Written into a ``documents/`` sub-folder.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from .models import ReviewState
from .prisma import CHECKLIST_2020
from .agents.reporter import PRISMAReporter


def _csv(rows: list[list], header: list[str]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def protocol_md(state: ReviewState) -> str:
    p = state.protocol
    inc = "\n".join(f"- {c}" for c in p.inclusion_criteria) or "- (none)"
    exc = "\n".join(f"- {c}" for c in p.exclusion_criteria) or "- (none)"
    kw = "; ".join(" OR ".join(g) for g in p.search.keywords) or "(see search log)"
    return f"""# Review protocol — {p.title}

**Registration.** {p.registration}  ·  **Contact.** {p.authors_contact or '—'}

## Objective / question ({p.pico.framework})
{p.question}

| {p.pico.framework} element | Specification |
|---------|---------------|
{chr(10).join(f"| {k} | {v} |" for k, v in p.pico.as_elements().items())}
| Eligible designs | {', '.join(p.pico.study_designs) or 'any'} |

## Eligibility criteria
**Inclusion**
{inc}

**Exclusion**
{exc}

## Information sources & search
Databases: {', '.join(p.search.sources)}. Date range: {p.search.date_from} → {p.search.date_to}.
Languages: {', '.join(p.search.languages)}. Concept groups: {kw}.

## Selection process
Two independent reviewers screen all records at title/abstract; conflicts are
resolved by an adjudicator. Eligible full texts are assessed against the criteria.

## Data collection & risk of bias
Structured extraction of design, population, intervention, comparator, sample
size and effect estimates. Risk of bias appraised with **{p.risk_of_bias.tool}**;
certainty of evidence by **GRADE**.

## Synthesis
{p.synthesis.model}-effects inverse-variance meta-analysis of the
{p.synthesis.effect_measure} (DerSimonian–Laird τ²; heterogeneity by I²/Q).
Small-study effects assessed by Egger's test and a funnel plot, where ≥3 studies.
"""


def search_log(state: ReviewState):
    hits = state.prisma.records_identified or {}
    rows = [[q.source, hits.get(q.source, ""), q.query, q.rationale]
            for q in state.strategy.queries]
    md = ["# Search log", "",
          f"Run {state.run_id} · date range {state.protocol.search.date_from} → "
          f"{state.protocol.search.date_to}", "",
          "| Database | Hits | Query | Rationale |", "|---|---|---|---|"]
    for q in state.strategy.queries:
        md.append(f"| {q.source} | {hits.get(q.source,'')} | `{q.query}` | {q.rationale} |")
    md.append(f"\n**Total records identified:** {state.prisma.records_total} · "
              f"**after de-duplication:** {state.prisma.records_screened} "
              f"(removed {state.prisma.duplicates_removed}).")
    return "\n".join(md), _csv(rows, ["database", "hits", "query", "rationale"])


def screening_log_csv(state: ReviewState) -> str:
    title = {r.uid: r.title for r in state.unique_records}
    doi = {r.uid: r.doi for r in state.unique_records}
    by = {}
    for d in state.screening:
        by.setdefault(d.uid, {})[d.reviewer] = d
    final_inc = set(state.included_after_screening)
    rows = []
    for uid in title:
        recs = by.get(uid, {})
        r1 = recs.get("reviewer_1")
        r2 = recs.get("reviewer_2")
        adj = recs.get("adjudicator")
        rows.append([
            uid, doi.get(uid, ""), title.get(uid, "")[:140],
            r1.decision.value if r1 else "", r2.decision.value if r2 else "",
            adj.decision.value if adj else "",
            "included" if uid in final_inc else "excluded",
            (r1.reason if r1 else "") or (adj.reason if adj else ""),
        ])
    return _csv(rows, ["uid", "doi", "title", "reviewer_1", "reviewer_2",
                       "adjudicator", "final", "reason"])


def excluded_fulltext(state: ReviewState):
    title = {r.uid: r.title for r in state.unique_records}
    rows = [[e.uid, title.get(e.uid, "")[:140], e.exclusion_reason]
            for e in state.eligibility if e.full_text_retrieved and not e.eligible]
    md = ["# Excluded full-text reports (with reasons) — PRISMA item 16b", ""]
    if rows:
        md += ["| Study | Reason for exclusion |", "|---|---|"]
        md += [f"| {t} | {r} |" for _, t, r in rows]
    else:
        md.append("_No full-text reports were excluded._")
    return "\n".join(md), _csv(rows, ["uid", "title", "exclusion_reason"])


def extraction_form_csv(state: ReviewState) -> str:
    rows = []
    for ex in state.extractions:
        eff = ex.effects[0] if ex.effects else None
        rows.append([
            ex.study_label, ex.design, ex.sample_size, ex.population,
            ex.intervention, ex.comparator, "; ".join(ex.outcomes),
            ex.gold_standard, "; ".join(ex.datasets), "; ".join(ex.baselines),
            eff.measure if eff else "", eff.estimate if eff else "",
            eff.ci_lower if eff else "", eff.ci_upper if eff else "",
            eff.se if eff else "", ex.notes,
        ])
    return _csv(rows, ["study", "design", "n", "population", "intervention",
                       "comparator", "outcomes", "gold_standard", "datasets",
                       "baselines", "measure", "estimate", "ci_lower", "ci_upper",
                       "se", "notes"])


def risk_of_bias_md(state: ReviewState) -> str:
    md = [f"# Risk-of-bias assessment ({state.protocol.risk_of_bias.tool}) — PRISMA item 18", ""]
    if not state.rob:
        md.append("_No included studies were appraised._")
        return "\n".join(md)
    for a in state.rob:
        md.append(f"## {a.study_label}  —  overall: **{a.overall}**")
        md.append("")
        md.append("| Domain | Judgement | Rationale |")
        md.append("|---|---|---|")
        for d in a.domains:
            md.append(f"| {d.name} | {d.judgement} | {d.rationale} |")
        if a.rationale:
            md.append(f"\n_Overall rationale:_ {a.rationale}")
        md.append("")
    return "\n".join(md)


def summary_of_findings_md(state: ReviewState) -> str:
    s = state.synthesis
    p = state.protocol

    # Preferred: a fully-derived multi-outcome GRADE table (one row per outcome).
    if s.grade_table:
        head = (
            "| Outcome | Studies (participants) | Effect | Risk of bias | "
            "Inconsistency | Indirectness | Imprecision | Other | Certainty (GRADE) | Importance |"
        )
        sep = "|" + "---|" * 10
        rows = [head, sep]
        for g in s.grade_table:
            part = f" ({g.n_participants})" if g.n_participants else ""
            rows.append(
                f"| {g.outcome} | {g.n_studies}{part} | {g.effect or '—'} | "
                f"{g.risk_of_bias} | {g.inconsistency} | {g.indirectness} | "
                f"{g.imprecision} | {g.other} | **{g.certainty}** | {g.importance or '—'} |"
            )
        table = "\n".join(rows)
        return (
            "# GRADE Summary of Findings — PRISMA item 22\n\n"
            f"**Question.** {p.question}\n\n"
            f"{table}\n\n"
            "GRADE certainty: ⊕⊕⊕⊕ high · ⊕⊕⊕◯ moderate · ⊕⊕◯◯ low · ⊕◯◯◯ very low.\n\n"
            f"**Overall certainty rationale.** {s.grade_rationale or '—'}\n"
        )

    # Fallback: single primary outcome (back-compatible).
    meta = s.meta_analysis
    n_part = sum(e.sample_size or 0 for e in state.extractions)
    effect = (f"{meta.measure} {meta.pooled_estimate} (95% CI {meta.ci_lower} to "
              f"{meta.ci_upper})" if meta else "not pooled")
    k = meta.k_studies if meta else len(state.included_studies)
    return f"""# GRADE Summary of Findings — PRISMA item 22

**Question.** {p.question}

| Outcome | № of studies (participants) | Effect ({p.synthesis.effect_measure}) | Heterogeneity | Certainty (GRADE) |
|---|---|---|---|---|
| {p.pico.outcome} | {k} ({n_part}) | {effect} | I² = {meta.i_squared if meta else '—'}% | **{s.grade_certainty or 'not rated'}** |

**Certainty rationale.** {s.grade_rationale or '—'}

**Publication bias.** {('Egger intercept=' + str(meta.eggers_intercept) + ', p=' + str(meta.eggers_p) + ', k=' + str(meta.eggers_k)) if meta and meta.eggers_p is not None else 'not formally tested'}.
"""


def declarations_md(state: ReviewState) -> str:
    """Journal end-matter declarations (CRediT, COI, funding, ethics, availability)."""
    p = state.protocol
    return f"""# Declarations

## Author contributions (CRediT taxonomy)
This review was produced by the NeuroAIon automated multi-agent engine. The
contributor roles map to the pipeline agents as follows:

| CRediT role | Contributor (agent) |
|---|---|
| Conceptualization | ProtocolArchitect (review question & protocol) |
| Methodology | ProtocolArchitect, SearchStrategist, EvidenceSynthesizer |
| Investigation (search) | SearchStrategist, DeduplicationAgent |
| Data curation (screening/extraction) | TitleAbstractScreener, DualScreenAdjudicator, FullTextEligibility, DataExtractor |
| Formal analysis | EvidenceSynthesizer (meta-analysis), RiskOfBiasAssessor |
| Visualization | Figure backend (forest, funnel, PRISMA, risk-of-bias) |
| Writing — original draft | PRISMAReporter |
| Writing — review & editing | PRISMAReporter, human corresponding author |
| Supervision | Human corresponding author ({p.authors_contact or '—'}) |

The human corresponding author is responsible for verifying every extracted
datum and the final manuscript prior to submission.

## Competing interests
The authors declare no competing interests.

## Funding
{p.registration if 'fund' in (p.registration or '').lower() else 'No specific grant from any funding agency in the public, commercial, or not-for-profit sectors was received for this review.'}

## Ethics approval
Not applicable — this is a secondary analysis of previously published studies;
no new human or animal data were collected.

## Registration and protocol
{p.registration}. The a-priori protocol is provided as `01_protocol.md` in this
dossier{'; a PROSPERO-ready registration form is provided as `prospero_registration.md`.' if p.prospero_export else '.'}

## Data and code availability
All data underlying this review (the full search corpus, screening decisions,
extracted data, and risk-of-bias assessments) are provided in machine-readable
form in this run directory (`state.json`, `sources/`, `documents/`,
`extractions.json`). A SHA-256 integrity manifest (`manifest.json`) accompanies
the dossier. The NeuroAIon engine source is available in the project repository.
"""


def reporting_summary_md(state: ReviewState) -> str:
    """A concise reporting summary tying the run's numbers to PRISMA items."""
    f = state.prisma
    s = state.synthesis
    n_meta = len(s.meta_analyses) if s.meta_analyses else (1 if s.meta_analysis else 0)
    return f"""# Reporting summary

| Item | Value |
|---|---|
| Records identified (databases) | {f.records_from_databases or f.records_total} |
| Records identified (registers) | {f.records_from_registers} |
| Duplicates removed | {f.duplicates_removed} |
| Records screened | {f.records_screened} |
| Records excluded at screening | {f.records_excluded_screening} |
| Reports sought for retrieval | {f.reports_sought} |
| Reports not retrieved | {f.reports_not_retrieved} |
| Reports assessed for eligibility | {f.reports_assessed} |
| Reports excluded (with reasons) | {sum(f.reports_excluded.values())} |
| **Studies included** | **{f.studies_included}** |
| Inter-rater agreement (Cohen's κ) | {state.cohen_kappa if state.cohen_kappa is not None else '—'} |
| Outcomes meta-analysed | {n_meta} |
| Risk-of-bias tool | {state.protocol.risk_of_bias.tool} |
| Certainty of evidence (GRADE) | {s.grade_certainty or 'not rated'} |

This summary supports PRISMA 2020 items 16a (study selection), 17 (characteristics),
18 (risk of bias), 20 (syntheses) and 22 (certainty).
"""


def extraction_template_csv() -> str:
    """A blank, ready-to-use data-extraction template (pilot/dual extraction)."""
    header = ["study_id", "first_author", "year", "doi", "design", "country",
              "n_total", "n_intervention", "n_comparator", "population",
              "intervention", "comparator", "outcome", "timepoint", "measure",
              "estimate", "ci_lower", "ci_upper", "se", "sd_intervention",
              "sd_comparator", "funding_source", "conflicts", "notes",
              "extractor", "checked_by"]
    buf = io.StringIO()
    csv.writer(buf).writerow(header)
    return buf.getvalue()


def supplementary_index_md(state: ReviewState) -> str:
    """An index of every artefact in the dossier (the supplementary materials map)."""
    return """# Supplementary materials — index

| File | Content | PRISMA item(s) |
|---|---|---|
| `01_protocol.md` | A-priori review protocol | 24 |
| `02_search_log.md/.csv` | Full per-database search strategy & hits | 6–7 |
| `03_screening_log.csv` | Per-record dual screening + adjudication | 8 |
| `04_excluded_full_text.md/.csv` | Excluded reports with reasons | 16b |
| `05_data_extraction_form.csv` | Completed extraction for included studies | 9–10 |
| `05b_extraction_template.csv` | Blank extraction template | 9 |
| `06_risk_of_bias.md` | Per-study risk-of-bias appraisal | 11, 18 |
| `07_summary_of_findings.md` | GRADE Summary of Findings | 15, 22 |
| `08_prisma_checklist.md` | PRISMA 2020 27-item checklist + locators | all |
| `08b_prisma_abstract_checklist.md` | PRISMA-for-Abstracts 12-item checklist | 2 |
| `09_method_comparison.md` | Benchmark map vs gold standards | 17, 19 |
| `10_declarations.md` | CRediT, COI, funding, ethics, availability | 24–27 |
| `11_reporting_summary.md` | Flow counts & key metrics | 16–22 |
| `../figures/` | Forest, funnel, PRISMA, risk-of-bias figures | 16, 18–21 |
| `../manifest.json` | SHA-256 integrity manifest | 27 |
"""


def method_comparison_md(state: ReviewState) -> str:
    """Benchmark leaderboard: each method vs its gold-standard reference networks."""
    md = ["# Method comparison vs gold standard — benchmark map", "",
          "Each included method, the data modality it was evaluated on, the "
          "gold-standard / ground-truth network(s) used for evaluation, the "
          "baselines it was compared against, and the reported outcome.", "",
          "| Study | Method (GNN type) | Data modality | Gold standard / benchmark | "
          "Baselines compared | Outcome metric | Reported result |",
          "|---|---|---|---|---|---|---|"]
    for ex in state.extractions:
        metrics = ", ".join(ex.outcomes) or "—"
        baselines = ", ".join(ex.baselines) or "—"
        md.append(f"| {ex.study_label} | {ex.intervention or '—'} | "
                  f"{ex.population or '—'} | {ex.gold_standard or '—'} | "
                  f"{baselines} | {metrics} | {(ex.notes or '—')[:120]} |")
    if not state.extractions:
        md.append("| _no included studies_ | | | | | | |")
    return "\n".join(md)


def prisma_checklist_md(state: ReviewState) -> str:
    cov = PRISMAReporter.coverage_map()
    md = ["# PRISMA 2020 checklist", "", "| # | Item | Reported in |", "|---|---|---|"]
    for num, name, _ in CHECKLIST_2020:
        md.append(f"| {num} | {name} | {cov.get(num, 'report')} |")
    return "\n".join(md)


def write_documents(out_dir: Path, state: ReviewState) -> list[Path]:
    """Write the full document dossier into ``out_dir/documents/``."""
    d = Path(out_dir) / "documents"
    d.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def w(name: str, content: str):
        path = d / name
        path.write_text(content, encoding="utf-8")
        written.append(path)

    from .prisma import abstract_checklist_markdown
    search_md, search_csv = search_log(state)
    excl_md, excl_csv = excluded_fulltext(state)
    w("01_protocol.md", protocol_md(state))
    w("02_search_log.md", search_md)
    w("02_search_log.csv", search_csv)
    w("03_screening_log.csv", screening_log_csv(state))
    w("04_excluded_full_text.md", excl_md)
    w("04_excluded_full_text.csv", excl_csv)
    w("05_data_extraction_form.csv", extraction_form_csv(state))
    w("05b_extraction_template.csv", extraction_template_csv())
    w("06_risk_of_bias.md", risk_of_bias_md(state))
    w("07_summary_of_findings.md", summary_of_findings_md(state))
    w("08_prisma_checklist.md", prisma_checklist_md(state))
    w("08b_prisma_abstract_checklist.md", abstract_checklist_markdown())
    w("09_method_comparison.md", method_comparison_md(state))
    w("10_declarations.md", declarations_md(state))
    w("11_reporting_summary.md", reporting_summary_md(state))
    w("00_supplementary_index.md", supplementary_index_md(state))
    return written
