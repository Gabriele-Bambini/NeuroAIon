"""Agent 8 — PRISMAReporter (PRISMA items 14–27) + QA attestation.

Produces a FULL, journal-length IMRaD manuscript (structured abstract,
introduction, methods, results, discussion, conclusions, strengths/limitations)
and a machine-checkable coverage map of the 27 PRISMA items. The prose is
strictly grounded in a deterministic dossier assembled from ``ReviewState`` —
the model is told to use only the supplied numbers and never to invent results.

Deterministic artefacts (flow diagram, characteristics table, forest table,
checklist) are assembled by ``neuroaion.report``; here we write the narrative
that surrounds them. ``write_prose`` returns a flat ``dict[str, str]`` whose keys
remain backward-compatible (``abstract``, ``background``, ``methods``,
``discussion``, ``conclusions``) while adding richer sections
(``introduction``, ``results``, ``strengths_limitations``,
``abstract_structured``).
"""
from __future__ import annotations

import json
from typing import Any, Optional

from ..models import (MetaAnalysisResult, ReviewState)
from .base import Agent, obj


def _num(x: Any) -> str:
    """Render a number compactly, or ``n/a`` for ``None``."""
    if x is None:
        return "n/a"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, float):
        return f"{x:.3g}"
    return str(x)


class PRISMAReporter(Agent):
    name = "PRISMAReporter"
    role = "Write the manuscript and attest PRISMA 2020 coverage."

    # ── grounded dossier builders ────────────────────────────────────────────
    @staticmethod
    def _rob_overall(state: ReviewState) -> dict[str, str]:
        return {r.uid: r.overall for r in state.rob}

    def _study_block(self, state: ReviewState) -> str:
        """One line per included study: label, design, n, RoB, key effects."""
        rob = self._rob_overall(state)
        lines: list[str] = []
        for ex in state.extractions:
            effs = "; ".join(
                f"{(e.outcome or '?')} {(e.measure or '')} "
                f"{_num(e.estimate)} [{_num(e.ci_lower)}, {_num(e.ci_upper)}]"
                f"{(' (' + e.subgroup + ')') if e.subgroup else ''}"
                for e in ex.effects[:6] if e.estimate is not None
            ) or "no quantitative effect reported"
            extras = []
            if ex.gold_standard:
                extras.append(f"benchmark={ex.gold_standard}")
            if ex.datasets:
                extras.append(f"datasets={', '.join(ex.datasets[:4])}")
            if ex.funding:
                extras.append(f"funding={ex.funding}")
            tail = (" | " + "; ".join(extras)) if extras else ""
            lines.append(
                f"- {ex.study_label or ex.uid}: design={ex.design or '?'}, "
                f"n={_num(ex.sample_size)}, population={ex.population or '?'}, "
                f"RoB(overall)={rob.get(ex.uid, '?')}; effects: {effs}{tail}"
            )
        return "\n".join(lines) or "(no extractable studies)"

    def _rob_summary(self, state: ReviewState) -> str:
        """Counts of overall RoB judgements + per-domain tallies."""
        if not state.rob:
            return "Risk of bias was not formally assessed."
        tally: dict[str, int] = {}
        for r in state.rob:
            tally[r.overall] = tally.get(r.overall, 0) + 1
        overall = ", ".join(f"{v} {k}" for k, v in sorted(tally.items()))
        tool = state.protocol.risk_of_bias.tool
        # Per-domain worst-offenders (first assessment's domain names as the template).
        domain_lines = []
        domain_tally: dict[str, dict[str, int]] = {}
        for r in state.rob:
            for d in r.domains:
                dt = domain_tally.setdefault(d.name, {})
                dt[d.judgement] = dt.get(d.judgement, 0) + 1
        for dname, dt in domain_tally.items():
            domain_lines.append(
                f"  · {dname}: " + ", ".join(f"{v} {k}" for k, v in sorted(dt.items())))
        dom = ("\n" + "\n".join(domain_lines)) if domain_lines else ""
        return (f"Tool: {tool}. Overall judgements across {len(state.rob)} studies: "
                f"{overall}.{dom}")

    @staticmethod
    def _meta_block(m: MetaAnalysisResult) -> str:
        """A rich, numbers-only block for one meta-analysed outcome."""
        het = (f"I²={_num(m.i_squared)}% "
               f"(95% CI {_num(m.i_squared_ci_lower)}–{_num(m.i_squared_ci_upper)}), "
               f"τ²={_num(m.tau_squared)} (τ={_num(m.tau)}), H={_num(m.H)}, "
               f"Q={_num(m.q_statistic)} (p={_num(m.q_p_value)})")
        infer = (f"{m.model}-effects, τ²-method={m.tau2_method}, "
                 f"HKSJ={'on' if m.knha else 'off'}, test={m.test_dist}"
                 f"{('(' + str(m.df) + ' df)') if m.df is not None else ''}")
        pi = (f" 95% prediction interval [{_num(m.pi_lower)}, {_num(m.pi_upper)}]."
              if m.pi_lower is not None else "")
        sub = ""
        if m.q_between is not None:
            rows = "; ".join(
                f"{s.get('subgroup')}: {s.get('estimate')} "
                f"[{s.get('ci_lower')}, {s.get('ci_upper')}] (k={s.get('k')}, "
                f"I²={s.get('i_squared')}%)" for s in (m.subgroups or [])
            )
            sub = (f" Subgroup contrast Q_between={_num(m.q_between)} "
                   f"(df={_num(m.q_between_df)}, p={_num(m.q_between_p)}); {rows}.")
        pub = ""
        if (m.eggers_p is not None or m.begg_p is not None
                or m.trimfill_missing is not None):
            pub = (" Publication-bias diagnostics — "
                   f"Egger intercept={_num(m.eggers_intercept)} (p={_num(m.eggers_p)}, "
                   f"k={_num(m.eggers_k)}); Begg τ={_num(m.begg_tau)} (p={_num(m.begg_p)}); "
                   f"trim-and-fill imputed {_num(m.trimfill_missing)} study(ies) on the "
                   f"{m.trimfill_side or '?'} side (adjusted estimate "
                   f"{_num(m.trimfill_adjusted_estimate)}).")
        loo = ""
        if m.leave_one_out:
            loo = (f" Leave-one-out range of the pooled estimate: "
                   + ", ".join(f"omit {r.get('omitted')}→{r.get('estimate')}"
                               for r in m.leave_one_out[:8]) + ".")
        return (
            f"OUTCOME '{m.outcome or 'primary'}' (k={m.k_studies}; {infer}): "
            f"pooled {m.measure}={_num(m.pooled_estimate)} "
            f"[95% CI {_num(m.ci_lower)}, {_num(m.ci_upper)}], "
            f"SE={_num(m.se_pooled)}, p={_num(m.p_value)}. Heterogeneity: {het}.{pi}"
            f"{sub}{pub}{loo}"
        )

    def _outcomes_block(self, state: ReviewState) -> str:
        metas = state.synthesis.meta_analyses or (
            [state.synthesis.meta_analysis] if state.synthesis.meta_analysis else [])
        if not metas:
            return ("No outcome had enough comparable studies for a meta-analysis; "
                    "the synthesis is narrative only.")
        return "\n\n".join(self._meta_block(m) for m in metas if m is not None)

    @staticmethod
    def _grade_block(state: ReviewState) -> str:
        rows = state.synthesis.grade_table
        if not rows:
            return (f"Overall GRADE certainty: "
                    f"{state.synthesis.grade_certainty or 'not rated'}. "
                    f"{state.synthesis.grade_rationale}")
        lines = []
        for r in rows:
            lines.append(
                f"- {r.outcome} ({r.design}, k={r.n_studies}, "
                f"n={_num(r.n_participants)}): RoB={r.risk_of_bias}, "
                f"inconsistency={r.inconsistency}, indirectness={r.indirectness}, "
                f"imprecision={r.imprecision}, other={r.other} → "
                f"certainty={r.certainty}; {r.effect}; importance={r.importance}")
        return ("GRADE Summary of Findings (deterministically derived):\n"
                + "\n".join(lines)
                + f"\nPrimary-outcome certainty: "
                  f"{state.synthesis.grade_certainty or 'not rated'}. "
                  f"Rationale: {state.synthesis.grade_rationale}")

    @staticmethod
    def _flow_block(state: ReviewState) -> str:
        f = state.prisma
        excl = "; ".join(f"{k}: {v}" for k, v in (f.reports_excluded or {}).items())
        return (
            f"Records identified: {f.records_total} "
            f"(databases {f.records_from_databases}, registers {f.records_from_registers}; "
            f"per-source {dict(f.records_identified)}). "
            f"Duplicates removed: {f.duplicates_removed}; "
            f"auto-excluded before screening: {f.auto_excluded}; "
            f"other removals: {f.removed_other_reasons}. "
            f"Records screened: {f.records_screened}; "
            f"excluded at title/abstract: {f.records_excluded_screening}. "
            f"Reports sought: {f.reports_sought}; not retrieved: {f.reports_not_retrieved}; "
            f"assessed for eligibility: {f.reports_assessed}; "
            f"excluded with reasons: {{{excl}}}. "
            f"Studies included: {f.studies_included} "
            f"(reports of included studies: {f.reports_of_included})."
        )

    @staticmethod
    def _search_block(state: ReviewState) -> str:
        p = state.protocol
        srch = p.search
        queries = "; ".join(
            f"{q.source}: {q.query}" for q in (state.strategy.queries or [])
        ) or "(strategy not recorded)"
        kappa = (f"{state.cohen_kappa}" if state.cohen_kappa is not None else "n/a")
        return (
            f"Databases/sources: {', '.join(srch.sources) or 'n/a'}. "
            f"Date range: {srch.date_from or 'open'} → {srch.date_to or 'present'}. "
            f"Languages: {', '.join(srch.languages) or 'any'}. "
            f"Per-source cap: {srch.max_records_per_source}. "
            f"Inter-rater agreement at title/abstract (Cohen's κ): {kappa}. "
            f"Registration: {p.registration}. "
            f"Boolean queries — {queries}."
        )

    @staticmethod
    def _eligibility_block(state: ReviewState) -> str:
        p = state.protocol
        inc = "; ".join(p.inclusion_criteria) or "(none specified)"
        exc = "; ".join(p.exclusion_criteria) or "(none specified)"
        elems = "; ".join(f"{k}={v}" for k, v in p.pico.as_elements().items())
        designs = ", ".join(p.pico.study_designs) or "any"
        return (f"Framework: {p.pico.framework} ({elems}). "
                f"Eligible designs: {designs}. "
                f"Inclusion: {inc}. Exclusion: {exc}.")

    # ── abstract flattening ──────────────────────────────────────────────────
    @staticmethod
    def _flatten_abstract(abstract: Any) -> str:
        """Turn a structured abstract object (or string) into one paragraph with
        run-in headers: ``Background: … Methods: … Results: … Conclusions: …``."""
        if isinstance(abstract, str):
            return abstract.strip()
        if not isinstance(abstract, dict):
            return str(abstract or "").strip()
        order = [
            ("background", "Background"),
            ("objectives", "Objectives"),
            ("methods", "Methods"),
            ("results", "Results"),
            ("conclusions", "Conclusions"),
        ]
        parts = []
        for key, label in order:
            val = (abstract.get(key) or "").strip() if abstract.get(key) else ""
            if val:
                parts.append(f"{label}: {val}")
        # Include any extra keys we did not anticipate, after the canonical ones.
        for key, val in abstract.items():
            if key not in {k for k, _ in order} and isinstance(val, str) and val.strip():
                parts.append(f"{key.capitalize()}: {val.strip()}")
        return " ".join(parts)

    # ── main entry point ─────────────────────────────────────────────────────
    def write_prose(self, state: ReviewState) -> dict[str, str]:
        s = state.synthesis
        primary = s.meta_analysis

        dossier = (
            f"REVIEW TITLE: {state.protocol.title}\n"
            f"REVIEW QUESTION: {state.protocol.question}\n\n"
            f"ELIGIBILITY & FRAMEWORK:\n{self._eligibility_block(state)}\n\n"
            f"INFORMATION SOURCES & SEARCH:\n{self._search_block(state)}\n\n"
            f"PRISMA FLOW (study selection counts):\n{self._flow_block(state)}\n\n"
            f"INCLUDED STUDIES ({len(state.included_studies)}):\n"
            f"{self._study_block(state)}\n\n"
            f"RISK OF BIAS SUMMARY:\n{self._rob_summary(state)}\n\n"
            f"PER-OUTCOME META-ANALYSES ({len(s.meta_analyses)} outcome(s)):\n"
            f"{self._outcomes_block(state)}\n\n"
            f"GRADE CERTAINTY:\n{self._grade_block(state)}\n\n"
            f"SYNTHESIS NARRATIVE (full, computed):\n{s.narrative}\n\n"
            f"LIMITATIONS (computed):\n{s.limitations}"
        )

        abstract_schema = obj({
            "background": {"type": "string"},
            "methods": {"type": "string"},
            "results": {"type": "string"},
            "conclusions": {"type": "string"},
        })
        schema = obj({
            "abstract": abstract_schema,
            "introduction": {"type": "string"},
            "methods": {"type": "string"},
            "results": {"type": "string"},
            "discussion": {"type": "string"},
            "conclusions": {"type": "string"},
            "strengths_limitations": {"type": "string"},
        })

        system = (
            "You are the senior corresponding author at a top computational-biology "
            "journal, writing a COMPLETE PRISMA 2020-compliant systematic review "
            "manuscript for peer review. Write formal, flowing scientific English in "
            "full PARAGRAPHS (never bullet fragments), at the depth and length a "
            "leading journal expects — multiple substantial paragraphs per section. "
            "Ground every quantitative claim STRICTLY in the numbers supplied in the "
            "dossier: never invent results, effect sizes, confidence intervals, "
            "p-values, certainty ratings, or counts; use only what is provided. Where "
            "you describe methods, name the actual estimators used (e.g. REML τ², "
            "Hartung–Knapp–Sidik–Jonkman small-sample inference, the 95% prediction "
            "interval, between-group Q for subgroups, Egger/Begg/trim-and-fill for "
            "reporting bias). Walk through EACH meta-analysed outcome in the Results. "
            "Do not overstate certainty beyond the GRADE rating provided."
        )
        user = (
            "Write the full manuscript prose for the systematic review described by "
            "the dossier below. Produce these sections:\n"
            "  • abstract: a STRUCTURED abstract object with background, methods, "
            "results, conclusions (results MUST report the real pooled effects, CIs, "
            "I², GRADE certainty from the dossier).\n"
            "  • introduction: 2–4 paragraphs giving the rationale and explicit "
            "objectives of the review (PRISMA items 3–4).\n"
            "  • methods: eligibility criteria, information sources, search strategy, "
            "selection process, data items, risk-of-bias method, and synthesis methods "
            "INCLUDING the actual statistical estimators (PRISMA items 5–13).\n"
            "  • results: study-selection numbers, study characteristics, risk-of-bias "
            "findings, the per-outcome quantitative syntheses WITH the real numbers, "
            "and reporting-bias assessment (PRISMA items 16–21).\n"
            "  • discussion: a general summary of the evidence, limitations of the "
            "evidence and of the review process, and comparison with prior work "
            "(PRISMA item 23).\n"
            "  • conclusions: implications for practice and for future research.\n"
            "  • strengths_limitations: a dedicated paragraph on the strengths and "
            "limitations of the review methodology.\n\n"
            "Use ONLY the figures in this dossier; if a value is 'n/a' say so rather "
            "than inventing it.\n\n"
            f"=== DOSSIER ===\n{dossier}\n=== END DOSSIER ==="
        )

        # Safe fallback so the five legacy keys are ALWAYS present strings.
        results_fallback = (
            f"{len(state.included_studies)} studies were included. "
            + (f"For the primary outcome '{primary.outcome or 'primary'}', the pooled "
               f"{primary.measure} ({primary.model}-effects, {primary.tau2_method} τ²) "
               f"was {_num(primary.pooled_estimate)} (95% CI {_num(primary.ci_lower)} to "
               f"{_num(primary.ci_upper)}; I²={_num(primary.i_squared)}%, "
               f"k={primary.k_studies}). {primary.interpretation}"
               if primary else
               "A meta-analysis was not performed owing to insufficient comparable data.")
        )
        fallback: dict[str, str] = {
            "abstract": (f"Background: {state.protocol.question} "
                         f"Methods: PRISMA 2020 systematic review. "
                         f"Results: {results_fallback} "
                         f"Conclusions: {s.limitations or 'See discussion.'}"),
            "abstract_structured": json.dumps({
                "background": state.protocol.question,
                "methods": "PRISMA 2020-compliant systematic review and meta-analysis.",
                "results": results_fallback,
                "conclusions": s.limitations or "See discussion.",
            }),
            "background": s.narrative or "",
            "introduction": s.narrative or "",
            "methods": self._eligibility_block(state) + " " + self._search_block(state),
            "results": results_fallback + " " + (s.narrative or ""),
            "discussion": s.narrative or "",
            "conclusions": s.limitations or "",
            "strengths_limitations": s.limitations or "",
        }

        try:
            out = self.ask_json(system, user, schema, max_tokens=16000)
        except Exception:  # noqa: BLE001
            return fallback

        # ── flatten + assemble backward-compatible dict ──────────────────────
        abstract_obj = out.get("abstract")
        abstract_flat = self._flatten_abstract(abstract_obj) or fallback["abstract"]
        introduction = (out.get("introduction") or "").strip()
        methods = (out.get("methods") or "").strip()
        results = (out.get("results") or "").strip()
        discussion = (out.get("discussion") or "").strip()
        conclusions = (out.get("conclusions") or "").strip()
        strengths = (out.get("strengths_limitations") or "").strip()

        if isinstance(abstract_obj, dict):
            abstract_structured: str = json.dumps(abstract_obj)
        elif isinstance(abstract_obj, str):
            abstract_structured = abstract_obj
        else:
            abstract_structured = fallback["abstract_structured"]

        return {
            # ── legacy keys (must be present, plain strings) ─────────────────
            "abstract": abstract_flat or fallback["abstract"],
            "background": introduction or fallback["background"],
            "methods": methods or fallback["methods"],
            "discussion": discussion or fallback["discussion"],
            "conclusions": conclusions or fallback["conclusions"],
            # ── richer keys for upgraded renderers ───────────────────────────
            "introduction": introduction or fallback["introduction"],
            "results": results or fallback["results"],
            "strengths_limitations": strengths or fallback["strengths_limitations"],
            "abstract_structured": abstract_structured,
        }

    @staticmethod
    def coverage_map() -> dict[str, str]:
        """Where each PRISMA 2020 item is addressed in this pipeline."""
        return {
            "1": "Title", "2": "Abstract", "3": "Background",
            "4": "ProtocolArchitect", "5": "ProtocolArchitect",
            "6": "SearchStrategist", "7": "SearchStrategist / Strategy table",
            "8": "Title/Abstract + Adjudicator", "9": "DataExtractor",
            "10": "DataExtractor", "11": "RiskOfBiasAssessor", "12": "Synthesis config",
            "13": "EvidenceSynthesizer", "14": "EvidenceSynthesizer (publication bias)",
            "15": "RiskOfBiasAssessor (GRADE)", "16": "PRISMA flow diagram",
            "17": "Characteristics table", "18": "Risk-of-bias table",
            "19": "Forest / per-study table", "20": "Synthesis results",
            "21": "Discussion (reporting bias)", "22": "GRADE certainty",
            "23": "Discussion", "24": "Methods (registration)", "25": "Funding",
            "26": "Competing interests", "27": "Data & code availability",
        }
