"""Agent 9 — EvidenceSynthesizer (PRISMA items 13, 20).

Journal-grade, multi-outcome evidence synthesis. Effect estimates are GROUPED by
outcome across studies and each outcome with enough studies is meta-analysed
deterministically in ``neuroaion.stats`` (REML τ², Hartung–Knapp inference,
prediction intervals, subgroup Q, leave-one-out, and publication-bias
diagnostics). A deterministic GRADE Summary-of-Findings table is derived from the
data (design, risk of bias, inconsistency, imprecision, publication bias); the
language model is used ONLY to write the narrative and to explain — never invent —
the computed certainty.
"""
from __future__ import annotations

from typing import Optional

from ..models import (EffectEstimate, ExtractionRecord, GradeRow,
                      MetaAnalysisResult, RoBAssessment, Synthesis)
from ..stats import eggers_test, funnel_points, meta_analyze
from .base import Agent, obj

# GRADE certainty ladder (best → worst) for deterministic downgrading.
_LADDER = ["high", "moderate", "low", "very low"]


def _downgrade(level: str, steps: int) -> str:
    i = _LADDER.index(level) if level in _LADDER else 0
    return _LADDER[min(len(_LADDER) - 1, i + max(0, steps))]


def _fmt(x) -> str:
    return f"{x:.2f}" if isinstance(x, (int, float)) else str(x)


class EvidenceSynthesizer(Agent):
    name = "EvidenceSynthesizer"
    role = "Synthesise findings qualitatively and (where possible) quantitatively."

    # ── outcome grouping ─────────────────────────────────────────────────────
    @staticmethod
    def _outcome_of(ex: ExtractionRecord, e: EffectEstimate) -> str:
        """Resolve the outcome label for an effect: its own, else the study's
        first declared outcome, else a generic placeholder."""
        name = (e.outcome or "").strip()
        if name:
            return name
        if ex.outcomes:
            first = (ex.outcomes[0] or "").strip()
            if first:
                return first
        return "Primary outcome"

    def _group_by_outcome(self, extractions: list[ExtractionRecord]):
        """Return an ordered dict outcome → (effects, labels)."""
        groups: dict[str, dict[str, list]] = {}
        for ex in extractions:
            label = ex.study_label or ex.uid
            for e in ex.effects:
                if e.estimate is None:
                    continue
                name = self._outcome_of(ex, e)
                g = groups.setdefault(name, {"effects": [], "labels": []})
                g["effects"].append(e)
                g["labels"].append(label)
        return groups

    # ── per-outcome meta-analysis ────────────────────────────────────────────
    def _meta_for_outcome(self, name: str, effects: list[EffectEstimate],
                          labels: list[str], cfg) -> Optional[MetaAnalysisResult]:
        k = len(effects)
        if k < cfg.min_studies_for_meta:
            return None
        # Per-outcome measure if the effects carry their own, else the config default.
        measures = {(e.measure or "").upper() for e in effects if e.measure}
        measure = measures.pop() if len(measures) == 1 else cfg.effect_measure
        random = cfg.model == "random"
        tau2_method = "REML" if random else "DL"
        knha = random and k >= 3
        has_subgroups = any(getattr(e, "subgroup", None) for e in effects)
        meta = meta_analyze(
            effects, measure=measure, model=cfg.model, labels=labels,
            tau2_method=tau2_method, knha=knha, prediction_interval_=True,
            subgroup=has_subgroups, leave_one_out_=(k >= 3),
            publication_bias=(cfg.publication_bias and k >= 3), outcome=name,
        )
        if meta is None:
            return None
        # Ensure publication-bias artefacts exist when requested even if the
        # meta_analyze path skipped them (defensive — k>=3 already covers this).
        if cfg.publication_bias and k >= 3 and not meta.funnel:
            meta.funnel = funnel_points(effects, measure)
            eg = eggers_test(effects)
            if eg:
                meta.eggers_intercept = eg["intercept"]
                meta.eggers_p = eg["p"]
                meta.eggers_k = eg["k"]
        self._enrich_interpretation(meta)
        return meta

    @staticmethod
    def _enrich_interpretation(meta: MetaAnalysisResult) -> None:
        """Significance + heterogeneity band + Egger sentence (per meta result)."""
        sig = meta.ci_lower is not None and meta.ci_upper is not None and (
            meta.ci_lower > 0 or meta.ci_upper < 0
        )
        i2 = meta.i_squared or 0
        band = ("low" if i2 < 40 else "moderate" if i2 < 60
                else "substantial" if i2 < 75 else "considerable")
        egger = ""
        if meta.eggers_p is not None:
            asym = "evidence of" if meta.eggers_p < 0.10 else "no strong evidence of"
            power = " (under-powered, k<10)" if (meta.eggers_k or 0) < 10 else ""
            egger = (f" Egger's test showed {asym} funnel asymmetry "
                     f"(intercept={meta.eggers_intercept}, p={meta.eggers_p}{power}).")
        pi = ""
        if meta.pi_lower is not None and meta.pi_upper is not None:
            pi = (f" The 95% prediction interval was "
                  f"[{meta.pi_lower}, {meta.pi_upper}].")
        meta.interpretation = (
            f"For '{meta.outcome or 'this outcome'}', the pooled effect "
            f"{'reached' if sig else 'did not reach'} statistical significance; "
            f"heterogeneity was {band} (I-squared={meta.i_squared}%, "
            f"tau-squared={meta.tau_squared}).{pi}{egger}"
        )

    # ── deterministic GRADE Summary-of-Findings ──────────────────────────────
    @staticmethod
    def _participants(effects: list[EffectEstimate],
                      extractions: list[ExtractionRecord], labels: list[str]) -> Optional[int]:
        total = 0
        seen = False
        for e in effects:
            n = (e.n_intervention or 0) + (e.n_comparator or 0)
            if n:
                total += n
                seen = True
        if seen:
            return total
        # Fall back to study sample sizes for the contributing studies.
        by_label = {(ex.study_label or ex.uid): ex.sample_size for ex in extractions}
        ss = [by_label.get(lab) for lab in set(labels)]
        ss = [s for s in ss if s]
        return sum(ss) if ss else None

    def _grade_row(self, name: str, meta: MetaAnalysisResult,
                   effects: list[EffectEstimate], labels: list[str],
                   extractions: list[ExtractionRecord],
                   rob_overall: dict[str, str]) -> GradeRow:
        # Designs of contributing studies → randomized vs observational.
        by_label = {(ex.study_label or ex.uid): ex for ex in extractions}
        designs = [(by_label[lab].design or "").lower()
                   for lab in labels if lab in by_label]
        randomized = bool(designs) and all(
            any(t in d for t in ("random", "rct", "trial")) for d in designs
        )
        design_label = "randomized trials" if randomized else "observational studies"
        start = "high" if randomized else "low"

        # RoB across the contributing studies (worst-case dominates).
        uid_by_label = {(ex.study_label or ex.uid): ex.uid for ex in extractions}
        overalls = [rob_overall.get(uid_by_label.get(lab, ""), "")
                    for lab in labels]
        n_high = sum(1 for o in overalls if o == "high")
        n_some = sum(1 for o in overalls if o == "some concerns")
        if n_high:
            rob_judge, rob_steps = "serious", 1
        elif n_some:
            rob_judge, rob_steps = "not serious", 0
        else:
            rob_judge, rob_steps = "not serious", 0

        # Inconsistency from I².
        i2 = meta.i_squared or 0
        if i2 > 75:
            incons_judge, incons_steps = "very serious", 2
        elif i2 > 50:
            incons_judge, incons_steps = "serious", 1
        else:
            incons_judge, incons_steps = "not serious", 0

        # Imprecision: CI crosses the null OR few participants.
        crosses_null = (meta.ci_lower is not None and meta.ci_upper is not None
                        and meta.ci_lower <= 0 <= meta.ci_upper)
        n_part = self._participants(effects, extractions, labels)
        few = n_part is not None and n_part < 400
        if crosses_null and few:
            imp_judge, imp_steps = "very serious", 2
        elif crosses_null or few:
            imp_judge, imp_steps = "serious", 1
        else:
            imp_judge, imp_steps = "not serious", 0

        # Publication bias: only assessable with enough studies (small-study tests
        # are underpowered below ~10 studies — GRADE/Cochrane guidance). Below that,
        # report as undetected rather than downgrading on noise.
        if (meta.k_studies or 0) >= 10:
            pub_bias = (meta.eggers_p is not None and meta.eggers_p < 0.10) or \
                       bool(meta.trimfill_missing)
            other_judge, other_steps = ("suspected", 1) if pub_bias else ("none", 0)
        else:
            other_judge, other_steps = "undetected (k<10)", 0

        steps = rob_steps + incons_steps + imp_steps + other_steps
        # Indirectness: not assessed deterministically (kept "not serious").
        certainty = _downgrade(start, steps)

        effect_str = (
            f"pooled {meta.measure} {_fmt(meta.pooled_estimate)} "
            f"(95% CI {_fmt(meta.ci_lower)} to {_fmt(meta.ci_upper)})"
            if meta.pooled_estimate is not None else "not estimable"
        )
        return GradeRow(
            outcome=name, n_studies=meta.k_studies, n_participants=n_part,
            design=design_label, risk_of_bias=rob_judge,
            inconsistency=incons_judge, indirectness="not serious",
            imprecision=imp_judge, other=other_judge, certainty=certainty,
            effect=effect_str, importance="critical",
        )

    # ── digest for the narrative writer ──────────────────────────────────────
    @staticmethod
    def _study_digest(extractions: list[ExtractionRecord],
                      rob_overall: dict[str, str]) -> str:
        lines = []
        for ex in extractions:
            eff = "; ".join(
                f"{e.outcome or '?'}={e.estimate} "
                f"[{e.ci_lower},{e.ci_upper}]" for e in ex.effects[:4]
            ) or "no quantitative effect"
            lines.append(
                f"- {ex.study_label or ex.uid}: design={ex.design or '?'}, "
                f"n={ex.sample_size}, RoB={rob_overall.get(ex.uid, '?')}; {eff}"
            )
        return "\n".join(lines) or "(no extractable studies)"

    @staticmethod
    def _outcome_digest(metas: list[MetaAnalysisResult]) -> str:
        if not metas:
            return "No outcome had enough comparable studies for meta-analysis."
        blocks = []
        for m in metas:
            sub = ""
            if m.q_between is not None:
                sub = (f" Subgroup test Q_between={m.q_between} "
                       f"(df={m.q_between_df}, p={m.q_between_p}).")
            pi = ""
            if m.pi_lower is not None:
                pi = f" 95% PI [{m.pi_lower}, {m.pi_upper}]."
            pub = ""
            if m.eggers_p is not None or m.trimfill_missing is not None:
                pub = (f" Publication bias: Egger p={m.eggers_p}, Begg p={m.begg_p}, "
                       f"trim-and-fill imputed {m.trimfill_missing} study(ies) "
                       f"(adjusted {m.trimfill_adjusted_estimate}).")
            blocks.append(
                f"OUTCOME '{m.outcome or 'primary'}' (k={m.k_studies}, "
                f"{m.model} effects, τ²-method={m.tau2_method}, "
                f"HKSJ={'on' if m.knha else 'off'}): pooled {m.measure}="
                f"{m.pooled_estimate} [95% CI {m.ci_lower}, {m.ci_upper}], "
                f"p={m.p_value}, I²={m.i_squared}% "
                f"(CI {m.i_squared_ci_lower}–{m.i_squared_ci_upper}), "
                f"τ²={m.tau_squared}.{pi}{sub}{pub}"
            )
        return "\n\n".join(blocks)

    # ── main entry point ─────────────────────────────────────────────────────
    def synthesize(self, extractions: list[ExtractionRecord],
                   rob: list[RoBAssessment]) -> Synthesis:
        cfg = self.protocol.synthesis
        rob_overall = {r.uid: r.overall for r in rob}

        groups = self._group_by_outcome(extractions)

        metas: list[MetaAnalysisResult] = []
        grade_rows: list[GradeRow] = []
        # Preserve insertion (study) order, which is deterministic.
        for name, g in groups.items():
            meta = self._meta_for_outcome(name, g["effects"], g["labels"], cfg)
            if meta is not None:
                metas.append(meta)
                grade_rows.append(self._grade_row(
                    name, meta, g["effects"], g["labels"], extractions, rob_overall))

        # Primary = most-studied outcome (ties → first encountered).
        primary: Optional[MetaAnalysisResult] = None
        primary_row: Optional[GradeRow] = None
        if metas:
            best_i = max(range(len(metas)), key=lambda i: metas[i].k_studies)
            # ``max`` already returns the first index on ties.
            primary = metas[best_i]
            primary_row = grade_rows[best_i]

        # Deterministic GRADE certainty from the primary outcome.
        det_certainty = primary_row.certainty if primary_row else ""
        det_rationale = ""
        if primary_row:
            det_rationale = (
                f"Starting certainty {('high' if primary_row.design == 'randomized trials' else 'low')} "
                f"for {primary_row.design}; risk of bias {primary_row.risk_of_bias}, "
                f"inconsistency {primary_row.inconsistency}, "
                f"indirectness {primary_row.indirectness}, "
                f"imprecision {primary_row.imprecision}, "
                f"other considerations {primary_row.other} → {primary_row.certainty}."
            )

        # ── narrative LLM call (numbers supplied, never invented) ────────────
        study_digest = self._study_digest(extractions, rob_overall)
        outcome_digest = self._outcome_digest(metas)
        n_outcomes = len(metas) if metas else 0

        schema = obj({
            "narrative": {"type": "string"},
            "grade_rationale": {"type": "string"},
            "limitations": {"type": "string"},
        })
        system = (
            "You are writing the quantitative and narrative synthesis for a "
            "PRISMA 2020 systematic review destined for a top computational-biology "
            "journal. Write thorough, formal, multi-paragraph scientific prose. Walk "
            "through EVERY meta-analysed outcome in turn: report the pooled effect, "
            "confidence interval, heterogeneity (I² with its CI and τ²), the prediction "
            "interval, any subgroup contrast, and publication-bias diagnostics, then "
            "interpret them. Integrate the per-study evidence. The GRADE certainty has "
            "ALREADY been computed deterministically and is provided to you — explain "
            "WHY it is what it is in plain language, but DO NOT change it and DO NOT "
            "invent any number beyond those supplied. Never overstate certainty."
        )
        user = (
            f"REVIEW QUESTION: {self.protocol.question}\n"
            f"OUTCOMES META-ANALYSED: {n_outcomes}\n\n"
            f"PER-OUTCOME POOLED RESULTS:\n{outcome_digest}\n\n"
            f"INCLUDED STUDIES (per-study design / n / risk of bias / effects):\n"
            f"{study_digest}\n\n"
            f"COMPUTED GRADE CERTAINTY (primary outcome '"
            f"{primary.outcome if primary else 'n/a'}'): "
            f"{det_certainty or 'not rated'}.\n"
            f"DETERMINISTIC GRADE RATIONALE: {det_rationale or 'n/a'}\n\n"
            "Write: (1) a thorough multi-paragraph synthesis narrative covering every "
            "outcome above; (2) a human-readable refinement of the GRADE rationale that "
            "explains the supplied certainty without altering it; (3) a limitations "
            "paragraph (evidence-level and review-process limitations)."
        )

        narrative = grade_rat = limits = ""
        try:
            out = self.ask_json(system, user, schema, max_tokens=6000)
            narrative = out.get("narrative", "") or ""
            grade_rat = out.get("grade_rationale", "") or ""
            limits = out.get("limitations", "") or ""
        except Exception:  # noqa: BLE001
            narrative = outcome_digest

        if not narrative:
            narrative = outcome_digest
        # The model may refine the rationale, but the deterministic one is the floor.
        grade_rat = grade_rat or det_rationale
        if det_rationale and det_rationale not in grade_rat:
            grade_rat = f"{grade_rat} ({det_rationale})" if grade_rat else det_rationale

        return Synthesis(
            narrative=narrative,
            meta_analysis=primary,
            meta_analyses=metas,
            grade_certainty=det_certainty,
            grade_rationale=grade_rat,
            grade_table=grade_rows,
            limitations=limits,
        )
