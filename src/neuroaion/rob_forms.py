"""Risk-of-bias appraisal forms — blank templates and completed assessments.

Two roles:

* ``write_blank_templates(folder)`` writes an empty, fill-in appraisal form for
  *every* supported instrument (RoB 2, ROBINS-I, ROBINS-E, QUADAS-2,
  Newcastle-Ottawa, AMSTAR-2, PROBAST, JBI) — a reusable library of blank
  signalling-question worksheets, one Markdown form + one CSV per tool.
* ``completed_form_md`` / ``write_completed_forms`` render a *filled* worksheet
  for each appraised study: every signalling question carries the recorded
  answer, each domain its judgement and the supporting quotation, and the form
  ends with the overall judgement — exactly the worksheet a reviewer fills by
  hand while reading the full text.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from . import rob_tools
from .models import RoBAssessment

_ANSWER_LADDER = "Yes / Probably yes / Probably no / No / No information"
_JUDGEMENTS = {
    "RoB2": "Low / Some concerns / High",
    "ROBINS-I": "Low / Moderate / Serious / Critical / No information",
    "ROBINS-E": "Low / Some concerns / High / Very high / No information",
    "QUADAS-2": "Low / Unclear / High",
    "Newcastle-Ottawa": "Good / Fair / Poor",
    "AMSTAR-2": "High / Moderate / Low / Critically low",
    "PROBAST": "Low / Unclear / High",
    "JBI": "Low / Unclear / High",
}


def _tools() -> list[str]:
    return list(rob_tools.SIGNALLING.keys())


def blank_form_md(tool: str) -> str:
    domains = rob_tools.domains_for(tool)
    ladder = _JUDGEMENTS.get(tool, "Low / Some concerns / High")
    out = [f"# Risk-of-bias worksheet — {tool}", "",
           f"**Study:** ____________________   **Reviewer:** ____________   **Date:** __________",
           "",
           f"_Answer each signalling question ({_ANSWER_LADDER}); record the supporting "
           f"text/quote; then judge the domain ({ladder})._", ""]
    for i, dom in enumerate(domains, 1):
        out.append(f"## Domain {i}. {dom}")
        out.append("")
        out.append("| # | Signalling question | Answer | Supporting text (quote / location) |")
        out.append("|---|---------------------|--------|------------------------------------|")
        for q in rob_tools.questions_for(tool, dom):
            qid, _, qtext = q.partition(" ")
            out.append(f"| {qid} | {qtext.strip() or q} |  |  |")
        applic = rob_tools.APPLICABILITY.get(tool, {}).get(dom) if hasattr(rob_tools, "APPLICABILITY") else None
        if applic:
            out.append("")
            out.append("_Applicability concern:_ " + "; ".join(applic))
        out.append("")
        out.append(f"**Domain {i} judgement:** ____________   ")
        out.append(f"**Support for judgement:** ________________________________________")
        out.append("")
    out.append(f"## Overall risk of bias")
    out.append(f"**Overall judgement ({ladder}):** ____________")
    out.append("")
    out.append("**Overall rationale:** ____________________________________________________")
    out.append("")
    return "\n".join(out)


def blank_form_csv(tool: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["domain", "question_id", "signalling_question", "answer",
                "supporting_text", "domain_judgement", "overall_judgement"])
    for dom in rob_tools.domains_for(tool):
        for q in rob_tools.questions_for(tool, dom):
            qid, _, qtext = q.partition(" ")
            w.writerow([dom, qid, qtext.strip() or q, "", "", "", ""])
    return buf.getvalue()


def write_blank_templates(folder: str | Path) -> list[Path]:
    """Write a blank worksheet (Markdown + CSV) for every supported instrument."""
    base = Path(folder)
    base.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    index = ["# Risk-of-bias worksheet library", "",
             "Blank, fill-in signalling-question worksheets for every supported "
             "instrument. Copy the worksheet for the design at hand and complete it "
             "while reading each study's full text.", "",
             "| Instrument | Use for | Form |", "|---|---|---|"]
    use = {
        "RoB2": "randomized trials", "ROBINS-I": "non-randomized studies of interventions",
        "ROBINS-E": "non-randomized studies of exposures", "QUADAS-2": "diagnostic accuracy studies",
        "Newcastle-Ottawa": "cohort / case-control studies", "AMSTAR-2": "systematic reviews",
        "PROBAST": "prediction-model studies", "JBI": "various designs (JBI checklists)",
    }
    for tool in _tools():
        slug = tool.replace("/", "-").replace(" ", "_")
        md = base / f"{slug}_blank.md"
        cv = base / f"{slug}_blank.csv"
        md.write_text(blank_form_md(tool), encoding="utf-8")
        cv.write_text(blank_form_csv(tool), encoding="utf-8")
        written += [md, cv]
        index.append(f"| {tool} | {use.get(tool, '—')} | `{md.name}` / `{cv.name}` |")
    (base / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return written


def completed_form_md(assessment: RoBAssessment) -> str:
    tool = assessment.tool
    ladder = _JUDGEMENTS.get(tool, "Low / Some concerns / High")
    out = [f"# Risk-of-bias worksheet — {tool}", "",
           f"**Study:** {assessment.study_label}", "",
           f"_Signalling-question appraisal ({ladder} per domain)._", ""]
    for i, dom in enumerate(assessment.domains, 1):
        out.append(f"## Domain {i}. {dom.name} — **{dom.judgement.title()}**")
        out.append("")
        if dom.signalling_answers:
            out.append("| Signalling question | Answer |")
            out.append("|---------------------|--------|")
            for q, a in dom.signalling_answers.items():
                out.append(f"| {q} | {a} |")
            out.append("")
        if dom.support_for_judgement:
            out.append(f"**Support for judgement.** {dom.support_for_judgement}")
            out.append("")
        elif dom.rationale:
            out.append(f"**Rationale.** {dom.rationale}")
            out.append("")
    out.append(f"## Overall risk of bias: **{assessment.overall.title()}**")
    out.append("")
    if assessment.rationale:
        out.append(assessment.rationale)
        out.append("")
    return "\n".join(out)


def write_completed_forms(folder: str | Path, assessments: list[RoBAssessment]) -> list[Path]:
    """Write one completed worksheet per appraised study + a traffic-light index."""
    base = Path(folder)
    base.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for i, a in enumerate(assessments, 1):
        slug = "".join(c if c.isalnum() else "_" for c in a.study_label)[:40] or f"study{i}"
        path = base / f"{i:02d}_{slug}_{a.tool.replace('/', '-')}.md"
        path.write_text(completed_form_md(a), encoding="utf-8")
        written.append(path)
    if assessments:
        domains = [d.name for d in assessments[0].domains]
        rows = ["# Completed risk-of-bias assessments — summary", "",
                "| Study | " + " | ".join(domains) + " | Overall |",
                "|" + "---|" * (len(domains) + 2)]
        for a in assessments:
            jud = {d.name: d.judgement for d in a.domains}
            rows.append("| " + a.study_label + " | "
                        + " | ".join(jud.get(d, "—") for d in domains)
                        + f" | {a.overall} |")
        idx = base / "00_summary.md"
        idx.write_text("\n".join(rows) + "\n", encoding="utf-8")
        written.append(idx)
    return written
