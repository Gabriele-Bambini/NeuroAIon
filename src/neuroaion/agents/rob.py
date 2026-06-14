"""Agent 8 — RiskOfBiasAssessor (PRISMA items 11–12, 15)."""
from __future__ import annotations

from ..frameworks import ROB_TOOLS as _DOMAINS
from ..models import ExtractionRecord, Record, RoBAssessment, RoBDomain
from .base import Agent, obj

_JUDGEMENT = {"type": "string", "enum": ["low", "some concerns", "high"]}


class RiskOfBiasAssessor(Agent):
    name = "RiskOfBiasAssessor"
    role = "Appraise risk of bias per study and contribute to GRADE certainty."

    def assess(self, record: Record, extraction: ExtractionRecord,
               full_text: str = "") -> RoBAssessment:
        tool = self.protocol.risk_of_bias.tool
        domains = _DOMAINS.get(tool, _DOMAINS["RoB2"])
        schema = obj({
            "domains": {
                "type": "array",
                "items": obj({
                    "name": {"type": "string"},
                    "judgement": _JUDGEMENT,
                    "rationale": {"type": "string"},
                }),
            },
            "overall": _JUDGEMENT,
            "rationale": {"type": "string"},
        })
        system = (
            f"You are appraising risk of bias using the {tool} tool. Judge each of these "
            f"domains as 'low', 'some concerns', or 'high': {domains}. Base each judgement "
            "on the study text; if information is missing, prefer 'some concerns'. Then give "
            "an overall judgement (high if any domain is high; some concerns if any domain "
            "is some concerns; otherwise low)."
        )
        body = full_text or record.abstract
        user = (
            f"STUDY: {extraction.study_label}\nDESIGN: {extraction.design}\n"
            f"TEXT: {body[:6000]}\n\nReturn the risk-of-bias assessment."
        )
        try:
            out = self.ask_json(system, user, schema, max_tokens=2500)
            dom = [RoBDomain(**d) for d in out.get("domains", [])]
            overall = out.get("overall", "some concerns")
            rationale = out.get("rationale", "")
        except Exception:  # noqa: BLE001
            dom = [RoBDomain(name=d, judgement="some concerns",
                             rationale="Insufficient information.") for d in domains]
            overall, rationale = "some concerns", "Default appraisal (assessment failed)."
        return RoBAssessment(
            uid=record.uid, study_label=extraction.study_label, tool=tool,
            domains=dom, overall=overall, rationale=rationale,
        )
