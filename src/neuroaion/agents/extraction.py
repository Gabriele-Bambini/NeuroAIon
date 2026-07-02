"""Agent 7 — DataExtractor (PRISMA items 9–10)."""
from __future__ import annotations

import re

from ..extraction_math import recompute
from ..models import EffectEstimate, ExtractionRecord, Record
from .base import Agent, obj

# The numbers a meta-analysis needs live in the Methods, Results, tables and the
# auto-harvested statistics digest — never the References. A flat prefix
# truncation routinely cut the tables (which are appended AFTER the body) off.
# So: preserve the number-dense digest in full, drop the references, and give the
# remaining budget to the results/methods-anchored body.
_MAX_CHARS = 24000
_DIGEST_CAP = 12000        # reserve for tables + captions + harvested statistics
_RESULT_HEADS = re.compile(
    r"\n\s*(results|outcomes?|efficacy|findings|methods?|statistical analysis|"
    r"table\s+\d)\b", re.IGNORECASE)
# Structured digest markers written by pdf_extract.as_working_text().
_DIGEST_START = re.compile(
    r"\n=== (EXTRACTED TABLES|FIGURE/TABLE CAPTIONS|REPORTED STATISTICS)", re.IGNORECASE)
_REFS_MARKER = re.compile(
    r"\n\s*(===\s*REFERENCES|references|bibliography)\b", re.IGNORECASE)


def _relevant_text(text: str) -> str:
    text = text or ""
    if len(text) <= _MAX_CHARS:
        return text

    # Split off the appended structured digest (tables/captions/statistics) so it
    # is never truncated away; the body is everything before it.
    dm = _DIGEST_START.search(text)
    body, digest = (text[:dm.start()], text[dm.start():]) if dm else (text, "")

    # Drop the reference list from whichever part carries it — pure budget waste.
    rb = _REFS_MARKER.search(body)
    if rb:
        body = body[:rb.start()]
    rd = _REFS_MARKER.search(digest)
    if rd:
        digest = digest[:rd.start()]
    digest = digest.strip()[:_DIGEST_CAP]
    body = body.strip()

    budget = _MAX_CHARS - len(digest) - 1        # -1 for the joining newline
    if len(body) > budget:
        first = _RESULT_HEADS.search(body)
        if first and first.start() > budget // 3:
            start = max(0, first.start() - budget // 4)
            body = body[start:start + budget]
        else:
            body = body[:budget]
    # body and digest are each within budget, so no further truncation clips the
    # number-dense digest.
    return (body + "\n" + digest) if digest else body

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
