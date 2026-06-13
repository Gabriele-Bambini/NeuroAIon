"""Agent 10 — PRISMAReporter (PRISMA items 14–27) + QA attestation.

Produces the manuscript prose (abstract, background, methods, discussion) and a
machine-checkable coverage map of the 27 PRISMA items. Deterministic artefacts
(flow diagram, characteristics table, forest table, checklist) are assembled by
``neuroaion.report``.
"""
from __future__ import annotations

from ..models import ReviewState
from .base import Agent, obj


class PRISMAReporter(Agent):
    name = "PRISMAReporter"
    role = "Write the manuscript and attest PRISMA 2020 coverage."

    def write_prose(self, state: ReviewState) -> dict[str, str]:
        s = state.synthesis
        meta = s.meta_analysis
        meta_line = (
            f"pooled {meta.measure}={meta.pooled_estimate} "
            f"[{meta.ci_lower}, {meta.ci_upper}], I²={meta.i_squared}%, k={meta.k_studies}"
            if meta else "no meta-analysis (insufficient comparable data)"
        )
        schema = obj({
            "abstract": {"type": "string"},
            "background": {"type": "string"},
            "methods": {"type": "string"},
            "discussion": {"type": "string"},
            "conclusions": {"type": "string"},
        })
        system = (
            "You are the lead author writing a PRISMA 2020-compliant systematic review "
            "manuscript. Write in formal scientific English. Be precise and do not "
            "overstate findings. Use the numbers provided; never invent results."
        )
        user = (
            f"PROTOCOL QUESTION: {state.protocol.question}\n"
            f"INCLUDED STUDIES: {len(state.included_studies)} "
            f"(from {state.prisma.records_total} records, "
            f"{state.prisma.duplicates_removed} duplicates removed)\n"
            f"QUANTITATIVE RESULT: {meta_line}\n"
            f"GRADE CERTAINTY: {s.grade_certainty or 'not rated'}\n"
            f"SYNTHESIS NARRATIVE: {s.narrative[:2000]}\n"
            f"LIMITATIONS: {s.limitations[:1000]}\n\n"
            "Write: a structured abstract (Background/Methods/Results/Conclusions), a "
            "background section, a methods summary (state PRISMA 2020 adherence and the "
            "search/screening/appraisal approach), a discussion, and conclusions."
        )
        try:
            return self.ask_json(system, user, schema, max_tokens=6000)
        except Exception:  # noqa: BLE001
            return {
                "abstract": "Background/Methods/Results/Conclusions unavailable (generation failed).",
                "background": "", "methods": "", "discussion": "", "conclusions": "",
            }

    @staticmethod
    def coverage_map() -> dict[str, str]:
        """Where each PRISMA 2020 item is addressed in this pipeline."""
        return {
            "1": "Title", "2": "Abstract", "3": "Background",
            "4": "ProtocolArchitect", "5": "ProtocolArchitect",
            "6": "SearchStrategist", "7": "SearchStrategist / Strategy table",
            "8": "Title/Abstract + Adjudicator", "9": "DataExtractor",
            "10": "DataExtractor", "11": "RiskOfBiasAssessor", "12": "Synthesis config",
            "13": "EvidenceSynthesizer", "14": "EvidenceSynthesizer (publication bias)",
            "15": "RiskOfBiasAssessor (GRADE)", "16": "PRISMA flow diagram",
            "17": "Characteristics table", "18": "Risk-of-bias table",
            "19": "Forest / per-study table", "20": "Synthesis results",
            "21": "Discussion (reporting bias)", "22": "GRADE certainty",
            "23": "Discussion", "24": "Methods (registration)", "25": "Funding",
            "26": "Competing interests", "27": "Data & code availability",
        }
