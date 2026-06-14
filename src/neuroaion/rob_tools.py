"""Signalling-question catalogue for the risk-of-bias instruments.

A pure-data module: no logic, no imports of project code. For every supported
risk-of-bias / quality-appraisal tool it lists the domains and, per domain, the
Cochrane SIGNALLING QUESTIONS with their canonical identifiers. The judgement
algorithms that consume these answers live in :mod:`neuroaion.rob_engine`; this
module only *declares the instrument*.

The design mirrors how RoB 2 is meant to be used in practice: a human (here, the
model) answers factual signalling questions, and a deterministic algorithm maps
those answers to a domain-level and overall judgement.

Exposed surface
---------------
``ANSWER_OPTIONS``      allowed answers to a signalling question.
``ANSWER_OPTIONS_NI``   same, with an explicit "No information" sentinel.
``SIGNALLING``          ``{tool: {domain: [questions]}}``.
``APPLICABILITY``       ``{tool: {domain: [applicability concerns]}}`` (QUADAS-2).
``NATIVE_LEVELS``       per-tool native judgement ladder (e.g. ROBINS-I 5-level).
``domains_for(tool)``   ordered domain list for a tool.
``questions_for(tool, domain)``  signalling questions for one domain.
``answer_options(tool)``  allowed answers for a tool's signalling questions.
"""
from __future__ import annotations

# Canonical answers to a Cochrane signalling question.
ANSWER_OPTIONS: list[str] = [
    "Yes", "Probably yes", "Probably no", "No", "No information",
]
# A few tools score with a plain "No information / NI" token; alias kept for clarity.
ANSWER_OPTIONS_NI = ANSWER_OPTIONS
NO_INFO = "No information"

# Newcastle-Ottawa is a star system; its "signalling questions" are the
# star-eligible items, answered Yes (star awarded) / No / No information.
NOS_OPTIONS: list[str] = ["Yes", "No", "No information"]

# Per-tool native judgement vocabularies (richer than the stored 3-level).
NATIVE_LEVELS: dict[str, list[str]] = {
    "RoB2": ["low", "some concerns", "high"],
    "ROBINS-I": ["low", "moderate", "serious", "critical", "no information"],
    "ROBINS-E": ["low", "some concerns", "high", "very high", "no information"],
    "QUADAS-2": ["low", "unclear", "high"],
    "Newcastle-Ottawa": ["good", "fair", "poor"],
    "AMSTAR-2": ["high", "moderate", "low", "critically low"],
    "PROBAST": ["low", "unclear", "high"],
    "JBI": ["low", "unclear", "high"],
}


# ── RoB 2 — randomized trials (Sterne et al. 2019) ───────────────────────────
_ROB2: dict[str, list[str]] = {
    "Randomization process": [
        "1.1 Was the allocation sequence random?",
        "1.2 Was the allocation sequence concealed until participants were "
        "enrolled and assigned to interventions?",
        "1.3 Did baseline differences between intervention groups suggest a "
        "problem with the randomization process?",
    ],
    "Deviations from intended interventions": [
        "2.1 Were participants aware of their assigned intervention during the "
        "trial?",
        "2.2 Were carers and people delivering the interventions aware of "
        "participants' assigned intervention during the trial?",
        "2.3 If yes/PY/NI to 2.1 or 2.2: were there deviations from the intended "
        "intervention that arose because of the trial context?",
        "2.4 If yes/PY/NI to 2.3: were these deviations likely to have affected "
        "the outcome?",
        "2.5 If yes/PY/NI to 2.4: were these deviations from intended "
        "intervention balanced between groups?",
        "2.6 Was an appropriate analysis used to estimate the effect of "
        "assignment to intervention?",
        "2.7 If no/PN/NI to 2.6: was there potential for a substantial impact "
        "(on the result) of the failure to analyse participants in the group to "
        "which they were randomized?",
    ],
    "Missing outcome data": [
        "3.1 Were data for this outcome available for all, or nearly all, "
        "participants randomized?",
        "3.2 If no/PN/NI to 3.1: is there evidence that the result was not "
        "biased by missing outcome data?",
        "3.3 If no/PN to 3.2: could missingness in the outcome depend on its "
        "true value?",
        "3.4 If yes/PY/NI to 3.3: is it likely that missingness in the outcome "
        "depended on its true value?",
    ],
    "Measurement of the outcome": [
        "4.1 Was the method of measuring the outcome inappropriate?",
        "4.2 Could measurement or ascertainment of the outcome have differed "
        "between intervention groups?",
        "4.3 If no/PN/NI to 4.1 and 4.2: were outcome assessors aware of the "
        "intervention received by study participants?",
        "4.4 If yes/PY/NI to 4.3: could assessment of the outcome have been "
        "influenced by knowledge of the intervention received?",
        "4.5 If yes/PY/NI to 4.4: is it likely that assessment of the outcome "
        "was influenced by knowledge of the intervention received?",
    ],
    "Selection of the reported result": [
        "5.1 Were the data that produced this result analysed in accordance with "
        "a pre-specified analysis plan finalized before unblinded outcome data "
        "were available?",
        "5.2 Is the numerical result being assessed likely to have been selected, "
        "on the basis of the results, from multiple eligible outcome "
        "measurements within the outcome domain?",
        "5.3 Is the numerical result being assessed likely to have been selected, "
        "on the basis of the results, from multiple eligible analyses of the "
        "data?",
    ],
}

# ── ROBINS-I — non-randomized studies of interventions (Sterne 2016) ─────────
_ROBINS_I: dict[str, list[str]] = {
    "Confounding": [
        "1.1 Is there potential for confounding of the effect of intervention "
        "in this study?",
        "1.4 Did the authors use an appropriate analysis method that controlled "
        "for all the important confounding domains?",
        "1.6 Did the authors control for any post-intervention variables that "
        "could have been affected by the intervention?",
    ],
    "Selection of participants": [
        "2.1 Was selection into the study unrelated to intervention or to the "
        "outcome?",
        "2.2 Do start of follow-up and start of intervention coincide for most "
        "participants?",
        "2.4 Were adjustment techniques used that are likely to correct for the "
        "presence of selection biases?",
    ],
    "Classification of interventions": [
        "3.1 Were intervention groups clearly defined?",
        "3.2 Was the information used to define intervention groups recorded at "
        "the start of the intervention?",
        "3.3 Could classification of intervention status have been affected by "
        "knowledge of the outcome or risk of the outcome?",
    ],
    "Deviations from intended interventions": [
        "4.1 Were there deviations from the intended intervention beyond what "
        "would be expected in usual practice?",
        "4.2 Were these deviations unbalanced between groups and likely to have "
        "affected the outcome?",
    ],
    "Missing data": [
        "5.1 Were outcome data available for all, or nearly all, participants?",
        "5.2 Were participants excluded due to missing data on intervention "
        "status?",
        "5.3 Were participants excluded due to missing data on other variables "
        "needed for the analysis?",
    ],
    "Measurement of outcomes": [
        "6.1 Could the outcome measure have been influenced by knowledge of the "
        "intervention received?",
        "6.2 Were outcome assessors aware of the intervention received by study "
        "participants?",
        "6.3 Were the methods of outcome assessment comparable across "
        "intervention groups?",
    ],
    "Selection of the reported result": [
        "7.1 Is the reported effect estimate likely to be selected, on the basis "
        "of the results, from multiple outcome measurements within the outcome "
        "domain?",
        "7.2 ... from multiple analyses of the intervention-outcome "
        "relationship?",
        "7.3 ... from different subgroups?",
    ],
}

# ── ROBINS-E — exposures (mirrors ROBINS-I, exposure-flavoured) ──────────────
_ROBINS_E: dict[str, list[str]] = {
    "Confounding": [
        "1.1 Is there potential for confounding of the effect of exposure?",
        "1.2 Did the analysis appropriately control the important confounders?",
    ],
    "Measurement of the exposure": [
        "2.1 Was exposure characterised using validated, reliable methods?",
        "2.2 Could exposure measurement have been affected by knowledge of, or "
        "presence of, the outcome (differential misclassification)?",
    ],
    "Selection of participants": [
        "3.1 Was selection into the study unrelated to exposure and outcome?",
        "3.2 Did start of follow-up and start of exposure coincide?",
    ],
    "Post-exposure interventions": [
        "4.1 Were post-exposure interventions that affect the outcome balanced "
        "across exposure groups?",
    ],
    "Missing data": [
        "5.1 Were outcome and exposure data available for nearly all "
        "participants?",
        "5.2 Is there evidence the result was not biased by missing data?",
    ],
    "Measurement of the outcome": [
        "6.1 Could the outcome measure have been influenced by knowledge of "
        "exposure status?",
        "6.2 Were outcome ascertainment methods comparable across exposure "
        "groups?",
    ],
    "Selection of the reported result": [
        "7.1 Was the result reported in accordance with a pre-specified analysis "
        "plan?",
        "7.2 Is the reported result likely selected from multiple measurements "
        "or analyses on the basis of the results?",
    ],
}

# ── QUADAS-2 — diagnostic-accuracy studies (Whiting 2011) ────────────────────
_QUADAS2: dict[str, list[str]] = {
    "Patient selection": [
        "Was a consecutive or random sample of patients enrolled?",
        "Was a case-control design avoided?",
        "Did the study avoid inappropriate exclusions?",
    ],
    "Index test": [
        "Were the index test results interpreted without knowledge of the "
        "results of the reference standard?",
        "If a threshold was used, was it pre-specified?",
    ],
    "Reference standard": [
        "Is the reference standard likely to correctly classify the target "
        "condition?",
        "Were the reference-standard results interpreted without knowledge of "
        "the results of the index test?",
    ],
    "Flow and timing": [
        "Was there an appropriate interval between index test and reference "
        "standard?",
        "Did all patients receive a reference standard?",
        "Did all patients receive the same reference standard?",
        "Were all patients included in the analysis?",
    ],
}
# QUADAS-2 also scores an applicability concern for the first three domains.
_QUADAS2_APPLIC: dict[str, list[str]] = {
    "Patient selection": [
        "Are there concerns that the included patients and setting do not match "
        "the review question?",
    ],
    "Index test": [
        "Are there concerns that the index test, its conduct or interpretation "
        "differ from the review question?",
    ],
    "Reference standard": [
        "Are there concerns that the target condition as defined by the "
        "reference standard does not match the review question?",
    ],
}

# ── Newcastle-Ottawa Scale — observational studies (star items) ──────────────
_NOS: dict[str, list[str]] = {
    "Selection": [
        "Is the case definition / exposed cohort representative (star)?",
        "Selection of controls / non-exposed cohort from the same population "
        "(star)?",
        "Ascertainment of exposure / secure record (star)?",
        "Demonstration that outcome of interest was not present at start (star)?",
    ],
    "Comparability": [
        "Comparability of cohorts/cases on the basis of the design or analysis: "
        "controls for the most important factor (star)?",
        "Comparability: controls for any additional factor (star)?",
    ],
    "Outcome/Exposure": [
        "Assessment of outcome / exposure: independent or record linkage (star)?",
        "Was follow-up long enough for outcomes to occur (star)?",
        "Adequacy of follow-up of cohorts / non-response rate comparable (star)?",
    ],
}

# ── Generic signalling questions for the remaining tools ─────────────────────
_GENERIC_QUESTIONS = [
    "Was this domain adequately addressed by the study's design and conduct?",
    "Is there evidence that this domain was handled in a way that protects "
    "against bias?",
    "Is the reporting on this domain transparent and free of important gaps?",
]


def _generic(domains: list[str]) -> dict[str, list[str]]:
    return {d: [f"{q} (domain: {d})" for q in _GENERIC_QUESTIONS] for d in domains}


# Domain lists for tools that only get a generic fallback (kept here so this
# module is self-contained and never imports frameworks at import time).
_FALLBACK_DOMAINS: dict[str, list[str]] = {
    "AMSTAR-2": ["Protocol registration", "Search adequacy", "Risk-of-bias methods",
                 "Meta-analysis methods", "Publication bias"],
    "JBI": ["Inclusion criteria", "Exposure measurement", "Confounding",
            "Outcome measurement", "Statistical analysis"],
    "PROBAST": ["Participants", "Predictors", "Outcome", "Analysis"],
}


SIGNALLING: dict[str, dict[str, list[str]]] = {
    "RoB2": _ROB2,
    "ROBINS-I": _ROBINS_I,
    "ROBINS-E": _ROBINS_E,
    "QUADAS-2": _QUADAS2,
    "Newcastle-Ottawa": _NOS,
    "AMSTAR-2": _generic(_FALLBACK_DOMAINS["AMSTAR-2"]),
    "JBI": _generic(_FALLBACK_DOMAINS["JBI"]),
    "PROBAST": _generic(_FALLBACK_DOMAINS["PROBAST"]),
}

APPLICABILITY: dict[str, dict[str, list[str]]] = {
    "QUADAS-2": _QUADAS2_APPLIC,
}


def _frameworks_domains(tool: str) -> list[str]:
    """Best-effort lookup of a tool's domains from frameworks.ROB_TOOLS.

    Imported lazily so this module has no hard dependency at import time. Used
    only as a last resort for tools we don't enumerate above.
    """
    try:
        from .frameworks import ROB_TOOLS
        return list(ROB_TOOLS.get(tool, []))
    except Exception:  # noqa: BLE001
        return []


def domains_for(tool: str) -> list[str]:
    """Return the ordered domain list for *tool* (RoB2 if unknown)."""
    if tool in SIGNALLING:
        return list(SIGNALLING[tool].keys())
    domains = _frameworks_domains(tool)
    if domains:
        return domains
    return list(SIGNALLING["RoB2"].keys())


def questions_for(tool: str, domain: str) -> list[str]:
    """Signalling questions for one domain (generic fallback if unknown)."""
    table = SIGNALLING.get(tool)
    if table and domain in table:
        return list(table[domain])
    # Unknown tool, or a known tool with an unlisted domain → generic.
    return [f"{q} (domain: {domain})" for q in _GENERIC_QUESTIONS]


def signalling_for(tool: str) -> dict[str, list[str]]:
    """Whole ``{domain: [questions]}`` map for a tool, synthesising for unknowns."""
    if tool in SIGNALLING:
        return {d: list(qs) for d, qs in SIGNALLING[tool].items()}
    domains = _frameworks_domains(tool) or list(SIGNALLING["RoB2"].keys())
    return _generic(domains)


def answer_options(tool: str) -> list[str]:
    """Allowed answers to a signalling question for *tool*."""
    if tool == "Newcastle-Ottawa":
        return list(NOS_OPTIONS)
    return list(ANSWER_OPTIONS)


def native_levels(tool: str) -> list[str]:
    """The tool's native judgement ladder (defaults to the 3-level scale)."""
    return list(NATIVE_LEVELS.get(tool, ["low", "some concerns", "high"]))
