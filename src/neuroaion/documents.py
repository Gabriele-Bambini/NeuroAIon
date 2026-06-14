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

## Objective / question (PICO)
{p.question}

| Element | Specification |
|---------|---------------|
| Population | {p.pico.population} |
| Intervention/Exposure | {p.pico.intervention} |
| Comparator | {p.pico.comparator} |
| Outcome | {p.pico.outcome} |
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
            ex.intervention, ex.comparator,
            "; ".join(ex.outcomes), eff.measure if eff else "",
            eff.estimate if eff else "", eff.ci_lower if eff else "",
            eff.ci_upper if eff else "", eff.se if eff else "", ex.funding,
        ])
    return _csv(rows, ["study", "design", "n", "population", "intervention",
                       "comparator", "outcomes", "measure", "estimate",
                       "ci_lower", "ci_upper", "se", "funding"])


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
    meta = s.meta_analysis
    p = state.protocol
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

    search_md, search_csv = search_log(state)
    excl_md, excl_csv = excluded_fulltext(state)
    w("01_protocol.md", protocol_md(state))
    w("02_search_log.md", search_md)
    w("02_search_log.csv", search_csv)
    w("03_screening_log.csv", screening_log_csv(state))
    w("04_excluded_full_text.md", excl_md)
    w("04_excluded_full_text.csv", excl_csv)
    w("05_data_extraction_form.csv", extraction_form_csv(state))
    w("06_risk_of_bias.md", risk_of_bias_md(state))
    w("07_summary_of_findings.md", summary_of_findings_md(state))
    w("08_prisma_checklist.md", prisma_checklist_md(state))
    return written
