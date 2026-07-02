"""Agent 1 — ProtocolArchitect (PRISMA items 4–7)."""
from __future__ import annotations

from ..frameworks import FRAMEWORKS
from ..models import (PICO, ReviewProtocol, RoBConfig, SearchConfig, SynthesisConfig)
from .base import Agent, obj


class ProtocolArchitect(Agent):
    name = "ProtocolArchitect"
    role = "Formulate the research question, PICO and eligibility contract."

    def propose_questions(self, topic: str, n: int = 4) -> list[dict]:
        """From an informal topic, propose several *formal* review questions in
        different frameworks (PICO/PECO/SPIDER/PCC/…), each with its elements.

        Returns a list of {framework, question, elements, rationale, review_type}.
        The user picks one to drive the review.
        """
        schema = obj({
            "proposals": {
                "type": "array",
                "items": obj({
                    "framework": {"type": "string"},
                    "review_type": {"type": "string"},
                    "question": {"type": "string"},
                    "elements": {
                        "type": "array",
                        "items": obj({"label": {"type": "string"},
                                      "value": {"type": "string"}}),
                    },
                    "rationale": {"type": "string"},
                }),
            }
        })
        system = (
            "You are a systematic-review methodologist. Given an informal research "
            f"topic, propose {n} DISTINCT formal review questions, each using a "
            "different, appropriate framework from this list: "
            f"{', '.join(FRAMEWORKS)}. For each, give the framework name, the review "
            "type (e.g. intervention / methodological-benchmark / scoping / diagnostic), "
            "a precise one-sentence formal question, the framework elements as "
            "label/value pairs, and a one-line rationale for why this framing fits."
        )
        try:
            out = self.ask_json(system, f"TOPIC: {topic}", schema, max_tokens=3000)
            props = []
            for p in out.get("proposals", []):
                props.append({
                    "framework": p.get("framework", "PICO"),
                    "review_type": p.get("review_type", ""),
                    "question": p.get("question", ""),
                    "elements": {e["label"]: e["value"] for e in p.get("elements", [])},
                    "rationale": p.get("rationale", ""),
                })
            return props
        except Exception:  # noqa: BLE001
            return []

    def derive_pico(self, question: str) -> dict:
        """Extract PICO/framework elements from a free-text research question.

        This is what turns "does AI help find polyps at colonoscopy?" into a
        structured, searchable protocol — the first step of a question-first
        review. Returns a dict with title, question, framework, PICO slots,
        eligible designs and seed inclusion/exclusion criteria.
        """
        schema = obj({
            "title": {"type": "string"},
            "question": {"type": "string"},
            "framework": {"type": "string"},
            "review_type": {"type": "string"},
            "population": {"type": "string"},
            "intervention": {"type": "string"},
            "comparator": {"type": "string"},
            "outcome": {"type": "string"},
            "study_designs": {"type": "array", "items": {"type": "string"}},
            "inclusion_criteria": {"type": "array", "items": {"type": "string"}},
            "exclusion_criteria": {"type": "array", "items": {"type": "string"}},
            "effect_measure": {"type": "string"},
        })
        system = (
            "You are a senior systematic-review methodologist. Turn the user's "
            "informal research question into a rigorous, answerable protocol. Choose "
            "the most appropriate framework (PICO for interventions, PECO for "
            "exposures, a DTA framing for diagnostic accuracy, PCC for scoping, "
            "etc.), fill each element precisely, name the eligible study designs, "
            "propose defensible inclusion/exclusion criteria, and pick the effect "
            "measure a biostatistician would use (RR/OR/HR/MD/SMD/PROP/DTA). Be "
            "specific and evidence-bound; do not invent a narrower question than asked."
        )
        try:
            return self.ask_json(system, f"RESEARCH QUESTION: {question}", schema, max_tokens=2500)
        except Exception:  # noqa: BLE001
            return {}

    def build(self, seed: dict) -> ReviewProtocol:
        # Question-first entry: if the reviewer supplied only a free-text question
        # (no structured PICO), derive the PICO from it before anything else.
        q_text = seed.get("question") or seed.get("title") or ""
        if q_text and q_text not in (None, "auto") and not seed.get("pico"):
            derived = self.derive_pico(q_text)
            if derived:
                seed = dict(seed)
                seed["pico"] = {
                    "framework": derived.get("framework", "PICO"),
                    "population": derived.get("population", ""),
                    "intervention": derived.get("intervention", ""),
                    "comparator": derived.get("comparator", ""),
                    "outcome": derived.get("outcome", ""),
                    "study_designs": derived.get("study_designs", []),
                }
                seed.setdefault("title", derived.get("title", "") or seed.get("title", ""))
                if seed.get("question") in (None, "", "auto"):
                    seed["question"] = derived.get("question", "")
                seed.setdefault("inclusion_criteria", derived.get("inclusion_criteria", []))
                seed.setdefault("exclusion_criteria", derived.get("exclusion_criteria", []))
                if derived.get("effect_measure"):
                    syn = dict(seed.get("synthesis") or {})
                    syn.setdefault("effect_measure", derived["effect_measure"])
                    seed["synthesis"] = syn

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
            citation_style=(seed.get("reporting") or {}).get("citation_style", "vancouver"),
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
