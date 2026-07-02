"""Agent 7 — DataExtractor (PRISMA items 9–10)."""
from __future__ import annotations

import re

from ..extraction_math import recompute
from ..models import EffectEstimate, ExtractionRecord, Record
from .base import Agent, obj

# The numbers a meta-analysis needs live in the Methods, Results and tables —
# never the References. A flat prefix truncation routinely cut them off. Keep a
# generous window, but if the text is longer, prefer the results-bearing
# sections over an arbitrary head slice.
_MAX_CHARS = 24000
_RESULT_HEADS = re.compile(
    r"\n\s*(results|outcomes?|efficacy|findings|methods?|statistical analysis|"
    r"table\s+\d)\b", re.IGNORECASE)


def _relevant_text(text: str) -> str:
    text = text or ""
    if len(text) <= _MAX_CHARS:
        return text
    # Drop everything from the reference list onward — it only wastes budget.
    cut = re.search(r"\n\s*(references|bibliography)\s*\n", text, re.IGNORECASE)
    if cut:
        text = text[:cut.start()]
        if len(text) <= _MAX_CHARS:
            return text
    # Anchor the window on the first results/methods heading so tables survive.
    first = _RESULT_HEADS.search(text)
    if first and first.start() > _MAX_CHARS // 3:
        start = max(0, first.start() - _MAX_CHARS // 4)
        return text[start:start + _MAX_CHARS]
    return text[:_MAX_CHARS]

_NUM = {"type": ["number", "null"]}
_INT = {"type": ["integer", "null"]}

_EFFECT = obj({
    "outcome": {"type": "string"},
    "measure": {"type": "string"},
    "estimate": _NUM,
    "ci_lower": _NUM,
    "ci_upper": _NUM,
    "se": _NUM,
    "n_intervention": _INT,
    "n_comparator": _INT,
    # Raw arm-level data — record it whenever the paper reports it so the
    # effect and its SE can be recomputed from first principles.
    "events_intervention": _INT,
    "events_comparator": _INT,
    "mean_intervention": _NUM, "sd_intervention": _NUM,
    "mean_comparator": _NUM, "sd_comparator": _NUM,
    "median_intervention": _NUM, "q1_intervention": _NUM, "q3_intervention": _NUM,
    "min_intervention": _NUM, "max_intervention": _NUM,
    "median_comparator": _NUM, "q1_comparator": _NUM, "q3_comparator": _NUM,
    "min_comparator": _NUM, "max_comparator": _NUM,
    "p_value": _NUM,
})

_SCHEMA = obj({
    "study_label": {"type": "string"},
    "design": {"type": "string"},
    "population": {"type": "string"},
    "intervention": {"type": "string"},
    "comparator": {"type": "string"},
    "sample_size": {"type": ["integer", "null"]},
    "outcomes": {"type": "array", "items": {"type": "string"}},
    "effects": {"type": "array", "items": _EFFECT},
    "funding": {"type": "string"},
    "notes": {"type": "string"},
})


class DataExtractor(Agent):
    name = "DataExtractor"
    role = "Extract structured study characteristics and quantitative results."

    def extract(self, record: Record, full_text: str = "") -> ExtractionRecord:
        system = (
            "You are extracting data from an included study for a meta-analysis. "
            "Capture design, population, intervention, comparator, sample size, the "
            "outcomes reported, and every quantitative effect estimate. Use the "
            f"protocol's effect measure ({self.protocol.synthesis.effect_measure}) "
            "where the study reports it. CRITICAL: whenever the paper reports the "
            "underlying raw data, record it in the raw fields — for binary outcomes "
            "the number of events and total in each arm (events_intervention, "
            "n_intervention, events_comparator, n_comparator); for continuous "
            "outcomes the group mean and SD (or median with IQR/range). The pooled "
            "effect will be recomputed from these raw numbers, so they take priority "
            "over any headline estimate. Report ONLY what the text states; use null "
            "for anything not reported. Never infer or fabricate numeric values."
        )
        body = _relevant_text(full_text or record.abstract)
        user = (
            f"STUDY\nTITLE: {record.title}\nYEAR: {record.year}\n"
            f"TEXT: {body}\n\nReturn the extraction."
        )
        label = record.citation().split(".")[0][:40]
        try:
            out = self.ask_json(system, user, _SCHEMA, max_tokens=3000)
            effects = [recompute(EffectEstimate(**e)) for e in out.get("effects", [])]
            return ExtractionRecord(
                uid=record.uid,
                study_label=out.get("study_label") or label,
                design=out.get("design", ""),
                population=out.get("population", ""),
                intervention=out.get("intervention", ""),
                comparator=out.get("comparator", ""),
                sample_size=out.get("sample_size"),
                outcomes=out.get("outcomes", []),
                effects=effects,
                funding=out.get("funding", ""),
                notes=out.get("notes", ""),
            )
        except Exception:  # noqa: BLE001
            return ExtractionRecord(uid=record.uid, study_label=label,
                                    notes="Extraction failed.")
