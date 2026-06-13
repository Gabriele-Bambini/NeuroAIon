"""Agent 5 — DualScreenAdjudicator (PRISMA items 8, 16).

Resolves disagreements between the two independent screeners. The orchestrator
supplies Reviewer 1 and Reviewer 2 decisions; this agent returns a single final
title/abstract decision per record and records the basis for resolution.
"""
from __future__ import annotations

from ..models import Decision, Record, ScreeningDecision
from .base import Agent, obj

_SCHEMA = obj({
    "decision": {"type": "string", "enum": ["include", "exclude"]},
    "reason": {"type": "string"},
})


class DualScreenAdjudicator(Agent):
    name = "DualScreenAdjudicator"
    role = "Adjudicate screening conflicts between the two reviewers."

    def resolve(self, record: Record, d1: ScreeningDecision,
                d2: ScreeningDecision) -> ScreeningDecision:
        # Clear agreement to include/exclude → accept it (no adjudication needed).
        if d1.decision == d2.decision and d1.decision in (Decision.INCLUDE, Decision.EXCLUDE):
            return ScreeningDecision(
                uid=record.uid, reviewer="adjudicator", decision=d1.decision,
                reason="Both reviewers agreed.", confidence=max(d1.confidence, d2.confidence),
            )

        # Any 'maybe', or an include/exclude split → adjudicate. Conservative default:
        # retain for full-text retrieval unless clearly excludable.
        system = (
            "You are the senior adjudicating reviewer. Two screeners disagreed (or were "
            "unsure) on a record. Make the final title/abstract decision using only the "
            "protocol criteria. Prefer 'include' (retrieve full text) when there is "
            "reasonable uncertainty; choose 'exclude' only when an exclusion criterion "
            "clearly applies from the title/abstract alone."
        )
        user = (
            f"RECORD\nTITLE: {record.title}\nABSTRACT: {record.abstract or '(none)'}\n\n"
            f"Reviewer 1: {d1.decision.value} — {d1.reason}\n"
            f"Reviewer 2: {d2.decision.value} — {d2.reason}\n\n"
            "Return the final decision."
        )
        try:
            out = self.ask_json(system, user, _SCHEMA, max_tokens=1200)
            decision = Decision(out.get("decision", "include"))
            reason = out.get("reason", "Adjudicated.")
        except Exception:  # noqa: BLE001
            # Conservative deterministic fallback: include unless both excluded.
            both_excl = d1.decision == Decision.EXCLUDE and d2.decision == Decision.EXCLUDE
            decision = Decision.EXCLUDE if both_excl else Decision.INCLUDE
            reason = "Resolved by conservative rule (retain on uncertainty)."
        return ScreeningDecision(
            uid=record.uid, reviewer="adjudicator", decision=decision, reason=reason,
            confidence=0.7,
        )
