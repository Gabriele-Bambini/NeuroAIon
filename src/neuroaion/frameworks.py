"""Supported review frameworks, risk-of-bias tools and citation styles.

NeuroAIon is framework-agnostic: the protocol declares a ``framework`` (PICO,
PECO, SPIDER, PCC, …) and a set of named ``elements``. Everything downstream —
prompts, documents, the manuscript — renders those elements generically, so any
review type works.
"""
from __future__ import annotations

# Framework → ordered element labels.
FRAMEWORKS: dict[str, list[str]] = {
    "PICO": ["Population", "Intervention", "Comparator", "Outcome"],
    "PECO": ["Population", "Exposure", "Comparator", "Outcome"],
    "PICOS": ["Population", "Intervention", "Comparator", "Outcome", "Study design"],
    "PECOS": ["Population", "Exposure", "Comparator", "Outcome", "Study design"],
    "PICOT": ["Population", "Intervention", "Comparator", "Outcome", "Time"],
    "PICOTS": ["Population", "Intervention", "Comparator", "Outcome", "Time", "Setting"],
    "SPIDER": ["Sample", "Phenomenon of Interest", "Design", "Evaluation", "Research type"],
    "PCC": ["Population", "Concept", "Context"],            # scoping reviews (JBI)
    "PIRD": ["Population", "Index test", "Reference test", "Diagnosis"],  # diagnostic
    "CoCoPop": ["Condition", "Context", "Population"],      # prevalence
    "SPICE": ["Setting", "Perspective", "Intervention", "Comparison", "Evaluation"],
    "ECLIPSE": ["Expectation", "Client", "Location", "Impact", "Professionals", "Service"],
}

# Risk-of-bias / quality-appraisal tools and their domains.
ROB_TOOLS: dict[str, list[str]] = {
    "RoB2": [
        "Randomization process", "Deviations from intended interventions",
        "Missing outcome data", "Measurement of the outcome",
        "Selection of the reported result",
    ],
    "ROBINS-I": [
        "Confounding", "Selection of participants", "Classification of interventions",
        "Deviations from intended interventions", "Missing data",
        "Measurement of outcomes", "Selection of the reported result",
    ],
    "ROBINS-E": [
        "Confounding", "Measurement of the exposure", "Selection of participants",
        "Post-exposure interventions", "Missing data",
        "Measurement of the outcome", "Selection of the reported result",
    ],
    "Newcastle-Ottawa": ["Selection", "Comparability", "Outcome/Exposure"],
    "QUADAS-2": ["Patient selection", "Index test", "Reference standard",
                 "Flow and timing"],
    "AMSTAR-2": ["Protocol registration", "Search adequacy", "Risk-of-bias methods",
                 "Meta-analysis methods", "Publication bias"],
    "JBI": ["Inclusion criteria", "Exposure measurement", "Confounding",
            "Outcome measurement", "Statistical analysis"],
    "PROBAST": ["Participants", "Predictors", "Outcome", "Analysis"],  # prediction models
}

CITATION_STYLES = ["vancouver", "apa", "harvard", "numeric"]

# Default literature sources (all free, no key). arXiv + Semantic Scholar are
# included so CS / methods preprints (e.g. graph-ML, sheaf models) are covered.
DEFAULT_SOURCES = ["pubmed", "europepmc", "crossref", "openalex",
                   "arxiv", "semanticscholar", "biorxiv"]

DEFAULT_DESIGNS = {
    "PICO": ["randomized controlled trial"],
    "PECO": ["cohort", "case-control"],
    "PIRD": ["diagnostic accuracy study"],
    "PCC": ["any"],
    "CoCoPop": ["cross-sectional"],
}


def normalize_framework(name: str) -> str:
    if not name:
        return "PICO"
    key = name.strip().upper()
    for k in FRAMEWORKS:
        if k.upper() == key:
            return k
    return "PICO"


def framework_elements(name: str) -> list[str]:
    return FRAMEWORKS.get(normalize_framework(name), FRAMEWORKS["PICO"])
