"""Agent 4 — TitleAbstractScreener (PRISMA item 8), acting as Reviewer 1."""
from __future__ import annotations

from ..models import Decision, Record, ScreeningDecision
from .base import Agent, obj

_SCHEMA = obj({
    "decision": {"type": "string", "enum": ["include", "exclude", "maybe"]},
    "reason": {"type": "string"},
    "confidence": {"type": "number"},
    "matched_criteria": {"type": "array", "items": {"type": "string"}},
})

_REVIEWER_STANCE = {
    "reviewer_1": "Be sensitive: when uncertain, lean toward 'maybe' rather than 'exclude'.",
    "reviewer_2": "Be specific: independently apply the criteria; do not assume the other reviewer.",
}


class TitleAbstractScreener(Agent):
    name = "TitleAbstractScreener"
    role = "Screen titles and abstracts against the eligibility criteria."

    def screen_one(self, record: Record, reviewer: str = "reviewer_1") -> ScreeningDecision:
        stance = _REVIEWER_STANCE.get(reviewer, "")
        system = (
            "You are a systematic-review screener performing title/abstract screening. "
            f"{stance} Decide include / exclude / maybe strictly from the protocol's "
            "inclusion and exclusion criteria. Cite which criteria drove the decision."
        )
        user = (
            f"RECORD\nTITLE: {record.title}\n"
            f"YEAR: {record.year}\nJOURNAL: {record.journal}\n"
            f"ABSTRACT: {record.abstract or '(no abstract available)'}\n\n"
            "Return your screening decision."
        )
        try:
            out = self.ask_json(system, user, _SCHEMA, max_tokens=1500)
            decision = Decision(out.get("decision", "maybe"))
            conf = float(out.get("confidence", 0.5))
        except Exception:  # noqa: BLE001
            decision, conf, out = Decision.MAYBE, 0.3, {}
        return ScreeningDecision(
            uid=record.uid, reviewer=reviewer, decision=decision,
            reason=out.get("reason", ""), confidence=conf,
            matched_criteria=out.get("matched_criteria", []),
        )
