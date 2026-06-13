"""Agent 7 — DataExtractor (PRISMA items 9–10)."""
from __future__ import annotations

from ..models import EffectEstimate, ExtractionRecord, Record
from .base import Agent, obj

_EFFECT = obj({
    "outcome": {"type": "string"},
    "measure": {"type": "string"},
    "estimate": {"type": ["number", "null"]},
    "ci_lower": {"type": ["number", "null"]},
    "ci_upper": {"type": ["number", "null"]},
    "se": {"type": ["number", "null"]},
    "n_intervention": {"type": ["integer", "null"]},
    "n_comparator": {"type": ["integer", "null"]},
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
            "outcomes reported, and every quantitative effect estimate with its "
            "confidence interval and group sizes. Use the protocol's effect measure "
            f"({self.protocol.synthesis.effect_measure}) where the study reports it. "
            "Report ONLY what the text states; use null for anything not reported. "
            "Never infer or fabricate numeric values."
        )
        body = full_text or record.abstract
        user = (
            f"STUDY\nTITLE: {record.title}\nYEAR: {record.year}\n"
            f"TEXT: {body[:8000]}\n\nReturn the extraction."
        )
        label = record.citation().split(".")[0][:40]
        try:
            out = self.ask_json(system, user, _SCHEMA, max_tokens=3000)
            effects = [EffectEstimate(**e) for e in out.get("effects", [])]
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
