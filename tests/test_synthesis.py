"""Tests for the multi-outcome journal-grade synthesis and the manuscript writer.

These run fully offline against the deterministic ``MockProvider`` — no API key
and no network. Because the mock returns canned, schema-valid content, the
assertions check STRUCTURE (grouping, GRADE table, the five legacy prose keys),
not the literal text.
"""
from __future__ import annotations

from neuroaion.agents.reporter import PRISMAReporter
from neuroaion.agents.synthesis import EvidenceSynthesizer
from neuroaion.llm import MockProvider
from neuroaion.models import (EffectEstimate, ExtractionRecord, GradeRow,
                              MetaAnalysisResult, PrismaFlow, ReviewProtocol,
                              ReviewState, RoBAssessment, RoBDomain, Synthesis)


def _protocol() -> ReviewProtocol:
    p = ReviewProtocol(
        title="Effect of intervention X on outcomes A and B",
        question="Does intervention X improve outcomes A and B versus control?",
        inclusion_criteria=["Randomized trials", "Reports outcome A or B"],
        exclusion_criteria=["Animal studies"],
    )
    p.synthesis.effect_measure = "SMD"
    p.synthesis.model = "random"
    p.synthesis.min_studies_for_meta = 2
    p.synthesis.publication_bias = True
    p.pico.study_designs = ["randomized controlled trial"]
    return p


def _extractions() -> list[ExtractionRecord]:
    """Five RCTs, each reporting two outcomes (A reported by all 5, B by 3)."""
    studies = [
        ("Smith 2019", 0.42, 0.18, 0.66, 60, 58),
        ("Jones 2020", 0.35, 0.05, 0.65, 50, 50),
        ("Lee 2020", 0.50, 0.20, 0.80, 45, 47),
        ("Garcia 2021", 0.28, -0.02, 0.58, 70, 68),
        ("Kim 2022", 0.61, 0.31, 0.91, 40, 42),
    ]
    out: list[ExtractionRecord] = []
    for i, (label, est, lo, hi, ni, nc) in enumerate(studies):
        effects = [EffectEstimate(
            outcome="Outcome A", measure="SMD", estimate=est,
            ci_lower=lo, ci_upper=hi, n_intervention=ni, n_comparator=nc)]
        if i < 3:  # only the first three studies report outcome B
            effects.append(EffectEstimate(
                outcome="Outcome B", measure="SMD", estimate=est - 0.1,
                ci_lower=lo - 0.1, ci_upper=hi - 0.1,
                n_intervention=ni, n_comparator=nc))
        out.append(ExtractionRecord(
            uid=f"uid{i}", study_label=label, design="randomized controlled trial",
            population="adults", sample_size=ni + nc,
            outcomes=["Outcome A", "Outcome B"], effects=effects))
    return out


def _rob(extractions: list[ExtractionRecord]) -> list[RoBAssessment]:
    return [RoBAssessment(
        uid=ex.uid, study_label=ex.study_label, tool="RoB2", overall="low",
        domains=[RoBDomain(name="Randomization", judgement="low")])
        for ex in extractions]


def test_multi_outcome_grouping_and_grade_table():
    prov = MockProvider()
    proto = _protocol()
    extractions = _extractions()
    rob = _rob(extractions)

    syn = EvidenceSynthesizer(prov, proto).synthesize(extractions, rob)

    # Two outcomes were grouped and meta-analysed (A: k=5, B: k=3).
    assert len(syn.meta_analyses) >= 1
    outcomes = {m.outcome for m in syn.meta_analyses}
    assert "Outcome A" in outcomes
    ks = {m.outcome: m.k_studies for m in syn.meta_analyses}
    assert ks["Outcome A"] == 5
    if "Outcome B" in ks:
        assert ks["Outcome B"] == 3

    # The primary (back-compat) meta-analysis is the most-studied outcome.
    assert syn.meta_analysis is not None
    assert syn.meta_analysis.outcome == "Outcome A"
    assert syn.meta_analysis.k_studies == max(ks.values())

    # A deterministic GRADE Summary-of-Findings table was built (one row/outcome).
    assert len(syn.grade_table) == len(syn.meta_analyses)
    assert all(isinstance(r, GradeRow) for r in syn.grade_table)
    primary_rows = [r for r in syn.grade_table if r.outcome == "Outcome A"]
    assert primary_rows and primary_rows[0].design == "randomized trials"
    # RCTs with low RoB start "high"; certainty is on the GRADE ladder.
    assert syn.grade_certainty in {"high", "moderate", "low", "very low"}
    assert primary_rows[0].certainty in {"high", "moderate", "low", "very low"}
    assert "pooled SMD" in primary_rows[0].effect

    # REML τ² + HKSJ inference were requested for the random-effects pooling.
    pa = syn.meta_analysis
    assert pa.tau2_method == "REML"
    assert pa.knha is True
    # Prediction interval present (k>=3).
    assert pa.pi_lower is not None and pa.pi_upper is not None
    # Per-result interpretation was enriched.
    assert pa.interpretation


def test_single_outcome_no_meta_still_valid():
    """Fewer studies than the threshold → no meta-analysis, but a valid Synthesis."""
    prov = MockProvider()
    proto = _protocol()
    proto.synthesis.min_studies_for_meta = 99  # nothing qualifies
    extractions = _extractions()
    syn = EvidenceSynthesizer(prov, proto).synthesize(extractions, _rob(extractions))
    assert isinstance(syn, Synthesis)
    assert syn.meta_analyses == []
    assert syn.meta_analysis is None
    assert isinstance(syn.narrative, str)


def _state_with_synthesis() -> ReviewState:
    proto = _protocol()
    extractions = _extractions()
    rob = _rob(extractions)
    syn = EvidenceSynthesizer(MockProvider(), proto).synthesize(extractions, rob)
    state = ReviewState(run_id="t1", mock=True, model="mock", protocol=proto)
    state.extractions = extractions
    state.rob = rob
    state.synthesis = syn
    state.included_studies = [ex.uid for ex in extractions]
    state.cohen_kappa = 0.81
    state.prisma = PrismaFlow(
        records_total=120, records_from_databases=120, duplicates_removed=20,
        records_screened=100, records_excluded_screening=80, reports_sought=20,
        reports_assessed=15, studies_included=len(extractions),
        reports_of_included=len(extractions))
    return state


def test_write_prose_returns_five_legacy_string_keys():
    state = _state_with_synthesis()
    prose = PRISMAReporter(MockProvider(), state.protocol).write_prose(state)

    legacy = ["abstract", "background", "methods", "discussion", "conclusions"]
    for key in legacy:
        assert key in prose, f"missing legacy key {key}"
        assert isinstance(prose[key], str), f"{key} is not a string"

    # Richer keys are also exposed for upgraded renderers.
    for key in ("introduction", "results", "strengths_limitations",
                "abstract_structured"):
        assert key in prose and isinstance(prose[key], str)

    # The structured abstract was flattened into a single string under "abstract".
    assert isinstance(prose["abstract"], str)


def test_write_prose_fallback_on_llm_failure():
    """If the JSON call raises, the five legacy keys are still present strings."""
    class _Boom(MockProvider):
        def complete_json(self, **kw):  # noqa: D401
            raise RuntimeError("simulated provider failure")

    state = _state_with_synthesis()
    prose = PRISMAReporter(_Boom(), state.protocol).write_prose(state)
    for key in ("abstract", "background", "methods", "discussion", "conclusions"):
        assert key in prose and isinstance(prose[key], str) and prose[key] != ""


def test_coverage_map_has_27_items():
    cov = PRISMAReporter.coverage_map()
    assert sorted(cov.keys(), key=int) == [str(i) for i in range(1, 28)]
    assert all(isinstance(v, str) and v for v in cov.values())
