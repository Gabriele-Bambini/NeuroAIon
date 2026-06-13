"""Agent 9 — EvidenceSynthesizer (PRISMA items 13, 20).

The pooled estimate and heterogeneity statistics are computed deterministically
in ``neuroaion.stats``; the model writes the narrative synthesis and assigns a
GRADE certainty rating informed by the risk-of-bias profile and heterogeneity.
"""
from __future__ import annotations

from ..models import (ExtractionRecord, MetaAnalysisResult, RoBAssessment,
                      Synthesis)
from ..stats import eggers_test, funnel_points, meta_analyze
from .base import Agent, obj


class EvidenceSynthesizer(Agent):
    name = "EvidenceSynthesizer"
    role = "Synthesise findings qualitatively and (where possible) quantitatively."

    def synthesize(self, extractions: list[ExtractionRecord],
                   rob: list[RoBAssessment]) -> Synthesis:
        cfg = self.protocol.synthesis

        # Gather the primary effect from each study (first usable effect estimate).
        effects, labels = [], []
        for ex in extractions:
            primary = next((e for e in ex.effects if e.estimate is not None), None)
            if primary is not None:
                effects.append(primary)
                labels.append(ex.study_label or ex.uid)

        meta: MetaAnalysisResult | None = None
        if len(effects) >= cfg.min_studies_for_meta:
            meta = meta_analyze(effects, measure=cfg.effect_measure,
                                model=cfg.model, labels=labels)

        # Publication-bias assessment (PRISMA item 14): Egger's test + funnel data.
        if meta and cfg.publication_bias:
            meta.funnel = funnel_points(effects, cfg.effect_measure)
            eg = eggers_test(effects)
            if eg:
                meta.eggers_intercept = eg["intercept"]
                meta.eggers_p = eg["p"]
                meta.eggers_k = eg["k"]

        # Build a compact evidence digest for the narrative writer.
        rob_overall = {r.uid: r.overall for r in rob}
        digest_lines = []
        for ex in extractions:
            digest_lines.append(
                f"- {ex.study_label}: design={ex.design or '?'}, n={ex.sample_size}, "
                f"rob={rob_overall.get(ex.uid, '?')}, "
                f"effects={[(e.outcome, e.estimate) for e in ex.effects][:3]}"
            )
        digest = "\n".join(digest_lines) or "(no extractable studies)"

        meta_line = (
            f"Pooled {meta.measure} ({meta.model} effects, k={meta.k_studies}) = "
            f"{meta.pooled_estimate} [95% CI {meta.ci_lower}, {meta.ci_upper}], "
            f"p={meta.p_value}, I²={meta.i_squared}%."
            if meta else "Meta-analysis not performed (insufficient comparable data)."
        )

        schema = obj({
            "narrative": {"type": "string"},
            "grade_certainty": {"type": "string",
                                "enum": ["high", "moderate", "low", "very low"]},
            "grade_rationale": {"type": "string"},
            "limitations": {"type": "string"},
        })
        system = (
            "You are writing the synthesis for a systematic review. Summarise the body of "
            "evidence faithfully, integrate the quantitative result if present, and assign "
            "a GRADE certainty (high/moderate/low/very low) considering risk of bias, "
            "inconsistency (heterogeneity), imprecision, indirectness and publication bias. "
            "Do not overstate certainty. Do not invent numbers beyond those provided."
        )
        user = (
            f"QUANTITATIVE RESULT:\n{meta_line}\n\n"
            f"INCLUDED STUDIES:\n{digest}\n\n"
            "Write a synthesis narrative, a GRADE certainty rating with rationale, and a "
            "limitations paragraph."
        )
        narrative = grade = grade_rat = limits = ""
        try:
            out = self.ask_json(system, user, schema, max_tokens=4000)
            narrative = out.get("narrative", "")
            grade = out.get("grade_certainty", "")
            grade_rat = out.get("grade_rationale", "")
            limits = out.get("limitations", "")
        except Exception:  # noqa: BLE001
            narrative = meta_line

        if meta:
            sig = meta.ci_lower is not None and meta.ci_upper is not None and (
                meta.ci_lower > 0 or meta.ci_upper < 0
            )
            egger = ""
            if meta.eggers_p is not None:
                asym = "evidence of" if meta.eggers_p < 0.10 else "no strong evidence of"
                power = " (under-powered, k<10)" if (meta.eggers_k or 0) < 10 else ""
                egger = (f" Egger's test showed {asym} funnel asymmetry "
                         f"(intercept={meta.eggers_intercept}, p={meta.eggers_p}{power}).")
            meta.interpretation = (
                f"The pooled effect {'reached' if sig else 'did not reach'} statistical "
                f"significance; heterogeneity was "
                f"{'low' if (meta.i_squared or 0) < 40 else 'substantial'} (I-squared="
                f"{meta.i_squared}%).{egger}"
            )

        return Synthesis(
            narrative=narrative, meta_analysis=meta,
            grade_certainty=grade, grade_rationale=grade_rat, limitations=limits,
        )
