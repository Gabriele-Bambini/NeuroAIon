"""Agent 6 — FullTextEligibility (PRISMA item 16b)."""
from __future__ import annotations

from ..models import EligibilityDecision, Record
from .base import Agent, obj

_SCHEMA = obj({
    "eligible": {"type": "boolean"},
    "exclusion_reason": {"type": "string"},
    "notes": {"type": "string"},
})


class FullTextEligibility(Agent):
    name = "FullTextEligibility"
    role = "Assess full texts for eligibility and record exclusion reasons."

    def assess(self, record: Record, full_text: str = "") -> EligibilityDecision:
        retrieved = bool(full_text) or bool(record.abstract)
        if not retrieved:
            return EligibilityDecision(
                uid=record.uid, eligible=False, full_text_retrieved=False,
                exclusion_reason="Full text not retrievable",
                notes="No full text or abstract available for assessment.",
            )
        system = (
            "You are assessing a study's full text (or, if unavailable, its abstract) "
            "for final eligibility against the protocol. If ineligible, give a single "
            "concise exclusion reason drawn from the exclusion criteria (e.g. 'Wrong "
            "population', 'Wrong comparator', 'No extractable outcome', 'Wrong design')."
        )
        body = full_text or record.abstract
        user = (
            f"STUDY\nTITLE: {record.title}\nYEAR: {record.year}\n"
            f"TEXT: {body[:6000]}\n\nReturn the eligibility decision."
        )
        try:
            out = self.ask_json(system, user, _SCHEMA, max_tokens=1500)
            eligible = bool(out.get("eligible", False))
            reason = "" if eligible else (out.get("exclusion_reason") or "Did not meet criteria")
            notes = out.get("notes", "")
        except Exception:  # noqa: BLE001
            eligible, reason, notes = False, "Assessment failed", ""
        return EligibilityDecision(
            uid=record.uid, eligible=eligible, full_text_retrieved=True,
            exclusion_reason=reason, notes=notes,
        )
