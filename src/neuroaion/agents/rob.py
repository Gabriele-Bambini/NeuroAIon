"""Agent 8 — RiskOfBiasAssessor (PRISMA items 11–12, 15).

Signalling-question-driven risk-of-bias appraisal. Instead of asking the model
for a flat per-domain verdict (which collapses to "some concerns" everywhere),
this agent asks the model to ANSWER the instrument's signalling questions as
factual yes/no/probably/no-information judgements grounded in the study text.
The domain and overall judgements are then DERIVED DETERMINISTICALLY in Python
by :mod:`neuroaion.rob_engine`, exactly as RoB 2 / ROBINS-I are meant to be
operated. The result is a differentiated, defensible, reproducible appraisal.
"""
from __future__ import annotations

from ..frameworks import ROB_TOOLS  # noqa: F401  (kept for compatibility)
from ..models import ExtractionRecord, Record, RoBAssessment, RoBDomain
from .. import rob_engine, rob_tools
from .base import Agent, obj

_MAX_TEXT = 9000


class RiskOfBiasAssessor(Agent):
    name = "RiskOfBiasAssessor"
    role = "Appraise risk of bias per study and contribute to GRADE certainty."

    def assess(self, record: Record, extraction: ExtractionRecord,
               full_text: str = "") -> RoBAssessment:
        configured = (self.protocol.risk_of_bias.tool or "auto").strip()
        if configured.lower() == "auto":
            # Match the instrument to THIS study's design (RoB2/ROBINS-I/QUADAS-2/…).
            tool = rob_tools.select_tool_for_design(
                extraction.design, getattr(self.protocol, "review_type", ""))
        else:
            tool = configured
        if tool not in rob_tools.SIGNALLING and tool not in ROB_TOOLS:
            tool = "RoB2"
        domains = rob_tools.domains_for(tool)
        options = rob_tools.answer_options(tool)
        study_label = extraction.study_label or record.title[:60] or record.uid

        schema = self._build_schema(domains, options)
        system = self._system_prompt(tool, options)
        user = self._user_prompt(tool, domains, extraction, record, full_text)

        try:
            out = self.ask_json(system, user, schema, max_tokens=4500)
            signalling_by_domain = self._parse_answers(tool, domains, out)
            extra = (out.get("notes") or "").strip()
            return rob_engine.build_assessment(
                tool=tool, study_label=study_label, uid=record.uid,
                signalling_by_domain=signalling_by_domain, extra_rationale=extra,
            )
        except Exception:  # noqa: BLE001
            return self._fallback(tool, study_label, record.uid, extraction)

    # ── prompt construction ──────────────────────────────────────────────────
    def _build_schema(self, domains: list[str], options: list[str]) -> dict:
        answer = {"type": "string", "enum": options}
        domain_item = obj({
            "domain": {"type": "string"},
            "answers": {
                "type": "array",
                "items": obj({
                    "question_id": {"type": "string"},
                    "answer": answer,
                }),
            },
            "support": {"type": "string"},   # short quote / evidence
        })
        return obj({
            "domains": {"type": "array", "items": domain_item},
            "notes": {"type": "string"},
        })

    def _system_prompt(self, tool: str, options: list[str]) -> str:
        opts = " / ".join(options)
        return (
            f"You are a methodologist applying the {tool} risk-of-bias instrument. "
            "Do NOT give an overall verdict yourself. Instead, ANSWER each "
            "numbered signalling question for every domain as a factual judgement, "
            f"choosing exactly one of: {opts}. Base every answer strictly on the "
            "study text; when the text does not say, answer 'No information'. For "
            "each domain also give a short 'support' quote or phrase from the text "
            "that justifies your answers. A deterministic algorithm will convert "
            "your answers into the domain and overall judgements, so accuracy and "
            "honesty on the signalling questions is what matters."
        )

    def _user_prompt(self, tool: str, domains: list[str],
                     extraction: ExtractionRecord, record: Record,
                     full_text: str) -> str:
        body = (full_text or record.abstract or "").strip()[:_MAX_TEXT]
        lines = [f"STUDY: {extraction.study_label or record.title}",
                 f"DESIGN: {extraction.design or 'not stated'}",
                 f"TOOL: {tool}", "",
                 "SIGNALLING QUESTIONS (answer each, by question_id):"]
        for d in domains:
            lines.append(f"\n[{d}]")
            for q in rob_tools.questions_for(tool, d):
                lines.append(f"  - {q}")
            for a in rob_tools.APPLICABILITY.get(tool, {}).get(d, []):
                lines.append(f"  - (applicability) {a}")
        lines += ["", "STUDY TEXT:", body or "(no text available)",
                  "", "Return one object per domain with the answers array."]
        return "\n".join(lines)

    # ── answer parsing ───────────────────────────────────────────────────────
    def _parse_answers(self, tool: str, domains: list[str],
                       out: dict) -> dict[str, dict[str, str]]:
        """Turn the model's response into {domain: {question_id: answer}}.

        Robust to: a domain name the model rephrased (matched case-insensitively
        / by substring), missing domains, and answers keyed either by the short
        question id (e.g. '2.4') or the full question text.
        """
        result: dict[str, dict[str, str]] = {d: {} for d in domains}
        support: dict[str, str] = {}
        lower = {d.lower(): d for d in domains}
        for item in (out.get("domains") or []):
            raw_name = (item.get("domain") or "").strip()
            canon = self._match_domain(raw_name, domains, lower)
            if canon is None:
                continue
            answers = item.get("answers") or []
            for a in answers:
                qid = (a.get("question_id") or "").strip()
                ans = (a.get("answer") or "").strip()
                if qid and ans:
                    result[canon][qid] = ans
            if item.get("support"):
                support[canon] = item["support"].strip()
        self._last_support = support  # used by fallback rationale, if any
        return result

    @staticmethod
    def _match_domain(raw: str, domains: list[str],
                      lower: dict[str, str]) -> str | None:
        if not raw:
            return None
        if raw in domains:
            return raw
        rl = raw.lower()
        if rl in lower:
            return lower[rl]
        for d in domains:
            if rl in d.lower() or d.lower() in rl:
                return d
        return None

    # ── conservative, VARIED fallback ────────────────────────────────────────
    def _fallback(self, tool: str, study_label: str, uid: str,
                  extraction: ExtractionRecord) -> RoBAssessment:
        """Build a *non-flat* default when the model call fails.

        We derive what we can from the design (e.g. randomized designs start at
        'some concerns' for blinding-related domains, observational designs flag
        confounding) and mark the rest honestly as insufficient information, so
        the output is still differentiated rather than uniform.
        """
        design = (extraction.design or "").lower()
        randomized = "random" in design or "rct" in design
        domains_out: list[RoBDomain] = []
        judgements: list[str] = []
        for d in rob_tools.domains_for(tool):
            j, support = self._fallback_domain(tool, d, randomized)
            domains_out.append(RoBDomain(
                name=d, judgement=j,
                rationale=f"Default appraisal ({tool}, no model output): {support}",
                support_for_judgement=support,
                signalling_answers={q: rob_tools.NO_INFO
                                    for q in rob_tools.questions_for(tool, d)},
            ))
            judgements.append(j)
        overall = rob_engine.derive_overall(tool, judgements)
        return RoBAssessment(
            uid=uid, study_label=study_label, tool=tool, domains=domains_out,
            overall=overall,
            rationale=("Conservative default appraisal: model assessment "
                       "unavailable; judgements reflect design-level priors and "
                       "insufficient reported information."),
        )

    @staticmethod
    def _fallback_domain(tool: str, domain: str, randomized: bool) -> tuple[str, str]:
        dl = domain.lower()
        # Observational confounding is a known high-risk concern by default.
        if "confound" in dl and not randomized:
            return ("high", "Non-randomized design: residual confounding likely "
                            "and not demonstrably controlled (insufficient detail).")
        if "randomiz" in dl and not randomized:
            return ("high", "Design is not described as randomized.")
        if any(k in dl for k in ("selection of the reported", "reporting")):
            return ("some concerns", "No pre-registered analysis plan confirmed; "
                                     "selective reporting cannot be excluded.")
        if any(k in dl for k in ("missing", "deviation", "measurement", "blind")):
            return ("some concerns", "Insufficient information on this domain.")
        return ("some concerns", "Insufficient reported information to judge this "
                                 "domain.")
