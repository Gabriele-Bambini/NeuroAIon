"""Agent 1 — ProtocolArchitect (PRISMA items 4–7)."""
from __future__ import annotations

from ..models import (PICO, ReviewProtocol, RoBConfig, SearchConfig, SynthesisConfig)
from .base import Agent, obj


class ProtocolArchitect(Agent):
    name = "ProtocolArchitect"
    role = "Formulate the research question, PICO and eligibility contract."

    def build(self, seed: dict) -> ReviewProtocol:
        pico = PICO(**(seed.get("pico") or {}))
        search = SearchConfig(**{k: v for k, v in (seed.get("search") or {}).items()})
        if search.date_to in (None, "auto"):
            from datetime import date
            search.date_to = date.today().isoformat()
        synth = SynthesisConfig(**(seed.get("synthesis") or {}))
        rob = RoBConfig(**(seed.get("risk_of_bias") or {}))

        protocol = ReviewProtocol(
            title=seed.get("title", "").strip(),
            question="" if seed.get("question") in (None, "auto") else seed.get("question", ""),
            pico=pico,
            inclusion_criteria=seed.get("inclusion_criteria", []),
            exclusion_criteria=seed.get("exclusion_criteria", []),
            search=search,
            synthesis=synth,
            risk_of_bias=rob,
            registration=(seed.get("reporting") or {}).get("registration", "Not registered"),
            authors_contact=(seed.get("reporting") or {}).get("authors_contact", ""),
            prospero_export=(seed.get("reporting") or {}).get("prospero_export", True),
        )

        # Let the model phrase the formal question and sanity-check the criteria,
        # but only *fill* gaps — the user's explicit choices are authoritative.
        if not protocol.question or not protocol.inclusion_criteria:
            schema = obj({
                "question": {"type": "string"},
                "suggested_inclusion": {"type": "array", "items": {"type": "string"}},
                "suggested_exclusion": {"type": "array", "items": {"type": "string"}},
            })
            user = (
                "Draft a single-sentence, answerable systematic-review question from "
                "the PICO above, and suggest any eligibility criteria that are missing. "
                "If the protocol already specifies criteria, return them unchanged."
            )
            try:
                out = self.ask_json(
                    "You are a senior systematic-review methodologist.", user, schema,
                    max_tokens=2000,
                )
                if not protocol.question:
                    protocol.question = out.get("question", "").strip()
                if not protocol.inclusion_criteria:
                    protocol.inclusion_criteria = out.get("suggested_inclusion", [])
                if not protocol.exclusion_criteria:
                    protocol.exclusion_criteria = out.get("suggested_exclusion", [])
            except Exception:  # noqa: BLE001
                pass

        if not protocol.question:
            protocol.question = (
                f"In {pico.population or 'the target population'}, what is the effect of "
                f"{pico.intervention or 'the intervention'} versus "
                f"{pico.comparator or 'comparator'} on {pico.outcome or 'the outcome'}?"
            )
        return protocol
