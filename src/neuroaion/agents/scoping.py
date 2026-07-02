"""Agent 0 — ScopingAgent: a preliminary probe that sharpens the protocol.

A methodologist never runs the definitive search first. They begin by *scoping*:
a quick, broad probe of one or two databases to learn how the field names the
concepts (so the real search captures every synonym), to judge how much evidence
exists, to surface the seminal studies, and to tighten the eligibility criteria
before a single record is formally screened. This agent reproduces that step, so
the review genuinely starts from a question and the full search is informed
rather than guessed.

The probe is deliberately small and read-only. Its findings only *fill gaps* in
the protocol — the reviewer's explicit choices always win — and everything it
suggests is recorded on the ``ScopingResult`` for the audit trail.
"""
from __future__ import annotations

from ..models import Record, ReviewProtocol, ScopingResult
from .base import Agent, obj

_SCHEMA = obj({
    "keyword_groups": {
        "type": "array",
        "items": {"type": "array", "items": {"type": "string"}},
    },
    "refined_inclusion": {"type": "array", "items": {"type": "string"}},
    "refined_exclusion": {"type": "array", "items": {"type": "string"}},
    "suggested_designs": {"type": "array", "items": {"type": "string"}},
    "date_from": {"type": ["string", "null"]},
    "seed_studies": {"type": "array", "items": {"type": "string"}},
    "rationale": {"type": "string"},
})


class ScopingAgent(Agent):
    name = "ScopingAgent"
    role = "Probe the literature to refine the PICO, vocabulary and eligibility."

    def scope(self, sample: list[Record] | None = None,
              probe_query: str = "") -> ScopingResult:
        """Refine the protocol from a small sample of probe records.

        ``sample`` is a handful of records returned by a broad preliminary query
        (title + abstract are enough). The agent reads them alongside the draft
        PICO and returns synonym clusters, sharpened criteria, the study designs
        actually used in the field, and a sensible lower date bound.
        """
        sample = sample or []
        snippets = []
        for r in sample[:25]:
            line = f"- {r.title}"
            if r.year:
                line += f" ({r.year})"
            if r.abstract:
                line += f": {r.abstract[:280]}"
            snippets.append(line)
        corpus = "\n".join(snippets) or "(no probe records available — refine from the PICO alone)"

        system = (
            "You are a systematic-review methodologist conducting a SCOPING search "
            "to inform the full protocol. From the draft PICO and the sample of "
            "records below, do four things: (1) build synonym clusters — one array "
            "per concept (population, intervention, comparator, outcome, design), "
            "listing every term, spelling, acronym and MeSH-style phrase the field "
            "uses, so the full search misses nothing; (2) sharpen the inclusion and "
            "exclusion criteria to remove ambiguity; (3) list the study designs that "
            "actually appear; (4) suggest a sensible earliest publication year if the "
            "evidence clearly postdates a technology or guideline. Ground every "
            "suggestion in the PICO and the sample; never invent studies."
        )
        user = (
            f"DRAFT PICO / QUESTION:\n{self.protocol.criteria_block()}\n\n"
            f"PROBE QUERY: {probe_query or '(none)'}\n\n"
            f"SAMPLE RECORDS ({len(sample)}):\n{corpus}\n\n"
            "Return the scoping analysis."
        )
        try:
            out = self.ask_json(system, user, _SCHEMA, max_tokens=3000)
        except Exception:  # noqa: BLE001
            return ScopingResult(probe_query=probe_query, estimated_volume=len(sample))

        groups = [[t for t in g if t] for g in out.get("keyword_groups", []) if g]
        return ScopingResult(
            keyword_groups=[g for g in groups if g],
            refined_inclusion=out.get("refined_inclusion", []),
            refined_exclusion=out.get("refined_exclusion", []),
            suggested_designs=out.get("suggested_designs", []),
            date_from=out.get("date_from") or None,
            seed_studies=out.get("seed_studies", []),
            estimated_volume=len(sample),
            rationale=out.get("rationale", ""),
            probe_query=probe_query,
        )

    def apply(self, protocol: ReviewProtocol, result: ScopingResult) -> ReviewProtocol:
        """Merge scoping findings into the protocol — filling gaps only."""
        if result.keyword_groups and not protocol.search.keywords:
            protocol.search.keywords = result.keyword_groups
        if result.refined_inclusion and not protocol.inclusion_criteria:
            protocol.inclusion_criteria = result.refined_inclusion
        if result.refined_exclusion and not protocol.exclusion_criteria:
            protocol.exclusion_criteria = result.refined_exclusion
        if result.suggested_designs and not protocol.pico.study_designs:
            protocol.pico.study_designs = result.suggested_designs
        if result.date_from and protocol.search.date_from in (None, "", "auto"):
            protocol.search.date_from = result.date_from
        return protocol
