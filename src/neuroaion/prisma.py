"""PRISMA 2020 flow-diagram counting, Mermaid rendering, and the 27-item checklist."""
from __future__ import annotations

from collections import Counter

from .models import Decision, PrismaFlow, ReviewState


def compute_flow(state: ReviewState) -> PrismaFlow:
    """Derive the PRISMA 2020 flow counts from the run state."""
    per_source = Counter(r.source for r in state.records)
    total = len(state.records)
    duplicates = total - len(state.unique_records)
    screened = len(state.unique_records)

    included_screening = set(state.included_after_screening)
    excluded_screening = screened - len(included_screening)

    sought = len(included_screening)
    not_retrieved = sum(
        1 for e in state.eligibility if not e.full_text_retrieved
    )
    assessed = sum(1 for e in state.eligibility if e.full_text_retrieved)

    excluded_reports = Counter(
        e.exclusion_reason or "Other"
        for e in state.eligibility
        if e.full_text_retrieved and not e.eligible
    )
    included = len(state.included_studies)

    # Split identification by databases vs. registers (trial/protocol registries).
    register_hints = ("clinicaltrials", "clinical-trials", "prospero", "ictrp",
                      "who-ictrp", "who ictrp", "isrctn", "anzctr", "drks",
                      "chictr", "ctri", "eudract", "registry", "register")
    from_registers = sum(v for k, v in per_source.items()
                         if any(h in k.lower() for h in register_hints))
    from_databases = total - from_registers

    return PrismaFlow(
        records_identified=dict(per_source),
        records_total=total,
        records_from_databases=from_databases,
        records_from_registers=from_registers,
        duplicates_removed=duplicates,
        records_screened=screened,
        records_excluded_screening=excluded_screening,
        reports_sought=sought,
        reports_not_retrieved=not_retrieved,
        reports_assessed=assessed,
        reports_excluded=dict(excluded_reports),
        studies_included=included,
        reports_of_included=included,
    )


def mermaid_flow(flow: PrismaFlow) -> str:
    """Render the PRISMA 2020 flow diagram as Mermaid (renders on GitHub)."""
    ident = "<br/>".join(f"{k}: {v}" for k, v in flow.records_identified.items()) or "—"
    excl_reports = "<br/>".join(
        f"{k}: {v}" for k, v in flow.reports_excluded.items()
    ) or "—"
    return f"""```mermaid
flowchart TB
    A["Records identified (n={flow.records_total})<br/>{ident}"]
    B["Records after duplicates removed (n={flow.records_screened})<br/>Duplicates removed (n={flow.duplicates_removed})"]
    C["Records screened (n={flow.records_screened})"]
    D["Records excluded (n={flow.records_excluded_screening})"]
    E["Reports sought for retrieval (n={flow.reports_sought})"]
    F["Reports not retrieved (n={flow.reports_not_retrieved})"]
    G["Reports assessed for eligibility (n={flow.reports_assessed})"]
    H["Reports excluded (n={sum(flow.reports_excluded.values())})<br/>{excl_reports}"]
    I["Studies included in review (n={flow.studies_included})"]
    A --> B --> C
    C --> D
    C --> E --> F
    E --> G
    G --> H
    G --> I
```"""


# PRISMA 2020 — 27 checklist items. The pipeline maps each to the agent/phase
# responsible, so the report can attest coverage.
CHECKLIST_2020: list[tuple[str, str, str]] = [
    ("1", "Title", "Identify the report as a systematic review."),
    ("2", "Abstract", "See the PRISMA 2020 abstract checklist."),
    ("3", "Rationale", "Describe the rationale in the context of existing knowledge."),
    ("4", "Objectives", "Provide an explicit statement of objective(s)/question(s)."),
    ("5", "Eligibility criteria", "Specify inclusion/exclusion criteria and groupings."),
    ("6", "Information sources", "Specify all databases/registers and the last search date."),
    ("7", "Search strategy", "Present full search strategies for all sources."),
    ("8", "Selection process", "Methods to decide inclusion (reviewers, independence, tools)."),
    ("9", "Data collection process", "Methods to collect data from reports."),
    ("10", "Data items", "List and define all outcomes and other variables sought."),
    ("11", "Study risk of bias assessment", "Methods to assess risk of bias."),
    ("12", "Effect measures", "Specify the effect measure(s) used."),
    ("13", "Synthesis methods", "Describe processes for synthesis incl. meta-analysis."),
    ("14", "Reporting bias assessment", "Methods to assess risk of bias due to missing results."),
    ("15", "Certainty assessment", "Methods to assess certainty (e.g. GRADE)."),
    ("16", "Study selection", "Report numbers screened/included with a flow diagram."),
    ("17", "Study characteristics", "Cite each included study and present its characteristics."),
    ("18", "Risk of bias in studies", "Present risk-of-bias assessments per study."),
    ("19", "Results of individual studies", "Present per-study results for each outcome."),
    ("20", "Results of syntheses", "Present results of each synthesis incl. heterogeneity."),
    ("21", "Reporting biases", "Present assessments of reporting bias."),
    ("22", "Certainty of evidence", "Present certainty (GRADE) for each outcome."),
    ("23", "Discussion", "Interpret results; discuss limitations and implications."),
    ("24", "Registration and protocol", "Provide registration info / protocol access."),
    ("25", "Support", "Describe sources of financial/non-financial support."),
    ("26", "Competing interests", "Declare competing interests."),
    ("27", "Availability of data/code", "Report availability of data, code, and materials."),
]


# Where in the manuscript each PRISMA 2020 item is located (section locators) —
# journals require a completed checklist citing the page/section for every item.
LOCATION_MAP: dict[str, str] = {
    "1": "Title", "2": "Abstract", "3": "Introduction", "4": "Introduction (Objectives)",
    "5": "Methods — Eligibility criteria", "6": "Methods — Information sources",
    "7": "Methods — Search strategy / Supplementary search log",
    "8": "Methods — Selection process", "9": "Methods — Data collection process",
    "10": "Methods — Data items", "11": "Methods — Risk-of-bias assessment",
    "12": "Methods — Effect measures", "13": "Methods — Synthesis methods",
    "14": "Methods — Reporting-bias assessment", "15": "Methods — Certainty assessment",
    "16": "Results — Study selection (Figure 1, PRISMA flow)",
    "17": "Results — Study characteristics (Table 1)",
    "18": "Results — Risk of bias (Figure, traffic-light)",
    "19": "Results — Results of individual studies (Forest plot)",
    "20": "Results — Results of syntheses", "21": "Results — Reporting biases (Funnel plot)",
    "22": "Results — Certainty of evidence (GRADE SoF)",
    "23": "Discussion", "24": "Methods — Registration and protocol",
    "25": "Funding", "26": "Competing interests", "27": "Data and code availability",
}

# PRISMA 2020 for Abstracts — 12-item checklist.
PRISMA_ABSTRACT_CHECKLIST: list[tuple[str, str, str]] = [
    ("1", "Title", "Identify the report as a systematic review."),
    ("2", "Objectives", "Provide an explicit statement of the main objective(s) or question(s)."),
    ("3", "Eligibility criteria", "Specify the inclusion and exclusion criteria for the review."),
    ("4", "Information sources", "Specify the information sources and the date last searched."),
    ("5", "Risk of bias", "Specify the methods used to assess risk of bias in the studies."),
    ("6", "Synthesis of results", "Specify the methods used to present and synthesise results."),
    ("7", "Included studies", "Give the total number of included studies and participants."),
    ("8", "Synthesis of results", "Present results for main outcomes, preferably with effect estimates and CIs."),
    ("9", "Limitations of evidence", "Provide a brief summary of the limitations of the evidence."),
    ("10", "Interpretation", "Provide a general interpretation of the results and important implications."),
    ("11", "Funding", "Specify the primary source of funding for the review."),
    ("12", "Registration", "Provide the register name and registration number."),
]


def checklist_markdown(coverage: dict[str, str] | None = None) -> str:
    """Render the 27-item checklist as a Markdown table.

    ``coverage`` optionally maps an item number → the manuscript section that
    reports it; when given it overrides the default location. The table shows a
    single human-readable "Location in report" column (as a completed PRISMA
    checklist does) — no internal component names.
    """
    coverage = coverage or {}
    lines = ["| # | Item | Description | Location in report |",
             "|---|------|-------------|--------------------|"]
    for num, name, desc in CHECKLIST_2020:
        loc = coverage.get(num) or LOCATION_MAP.get(num, "see report")
        lines.append(f"| {num} | {name} | {desc} | {loc} |")
    return "\n".join(lines)


def abstract_checklist_markdown() -> str:
    """Render the PRISMA-for-Abstracts 12-item checklist as a Markdown table."""
    lines = ["# PRISMA 2020 for Abstracts checklist (12 items)", "",
             "| # | Item | Description |", "|---|------|-------------|"]
    for num, name, desc in PRISMA_ABSTRACT_CHECKLIST:
        lines.append(f"| {num} | {name} | {desc} |")
    return "\n".join(lines)
