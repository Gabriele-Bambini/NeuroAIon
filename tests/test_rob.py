"""Tests for the signalling-question-driven risk-of-bias engine and figures.

These prove the engine is NOT flat: differing signalling answers yield different
domain and overall judgements, a clean study derives 'low' and a flawed study
derives 'high', the assessment carries signalling answers + support text, and
the publication figures write valid vector/raster files.
"""
from __future__ import annotations

from neuroaion import rob_engine as E
from neuroaion import rob_plots as P
from neuroaion import rob_tools as T
from neuroaion.agents.rob import RiskOfBiasAssessor
from neuroaion.llm import MockProvider
from neuroaion.models import (ExtractionRecord, Record, ReviewProtocol,
                              RoBAssessment, RoBConfig)

# ── Reusable signalling fixtures (RoB 2) ─────────────────────────────────────
LOW_SIG = {
    "Randomization process": {"1.1": "Yes", "1.2": "Yes", "1.3": "No"},
    "Deviations from intended interventions": {
        "2.1": "No", "2.2": "No", "2.6": "Yes"},
    "Missing outcome data": {"3.1": "Yes"},
    "Measurement of the outcome": {"4.1": "No", "4.2": "No", "4.3": "No"},
    "Selection of the reported result": {"5.1": "Yes", "5.2": "No", "5.3": "No"},
}
HIGH_SIG = {
    "Randomization process": {"1.1": "No", "1.2": "No", "1.3": "Yes"},
    "Deviations from intended interventions": {
        "2.1": "Yes", "2.5": "No", "2.6": "No"},
    "Missing outcome data": {"3.1": "No", "3.4": "Yes"},
    "Measurement of the outcome": {"4.1": "Yes"},
    "Selection of the reported result": {"5.1": "No", "5.2": "Yes"},
}
MID_SIG = {
    "Randomization process": {"1.1": "Yes", "1.2": "No information", "1.3": "No"},
    "Deviations from intended interventions": {
        "2.1": "No", "2.2": "No", "2.6": "Yes"},
    "Missing outcome data": {"3.1": "Yes"},
    "Measurement of the outcome": {"4.1": "No", "4.2": "No", "4.3": "No"},
    "Selection of the reported result": {"5.1": "Yes", "5.2": "No", "5.3": "No"},
}


# ── Catalogue ────────────────────────────────────────────────────────────────
def test_signalling_catalogue_covers_real_tools():
    assert T.domains_for("RoB2")[0] == "Randomization process"
    assert len(T.domains_for("RoB2")) == 5
    assert len(T.domains_for("ROBINS-I")) == 7
    assert len(T.domains_for("QUADAS-2")) == 4
    # Real signalling-question counts for RoB 2.
    assert len(T.questions_for("RoB2", "Deviations from intended interventions")) == 7
    assert len(T.questions_for("RoB2", "Missing outcome data")) == 4
    # Native ladders differ per instrument.
    assert "critical" in T.native_levels("ROBINS-I")
    # Generic fallback for an unlisted tool never crashes.
    assert T.questions_for("PROBAST", "Analysis")
    assert T.answer_options("RoB2")[0] == "Yes"


# ── Engine derivation ────────────────────────────────────────────────────────
def test_engine_is_not_flat_three_levels_derivable():
    low = E.build_assessment("RoB2", "Good 2020", "u1", LOW_SIG)
    high = E.build_assessment("RoB2", "Bad 2019", "u2", HIGH_SIG)
    mid = E.build_assessment("RoB2", "Mid 2021", "u3", MID_SIG)
    overalls = {low.overall, high.overall, mid.overall}
    # All three risk levels appear → the output is genuinely differentiated.
    assert overalls == {"low", "some concerns", "high"}
    assert low.overall == "low"
    assert high.overall == "high"
    assert mid.overall == "some concerns"


def test_low_study_all_domains_low():
    low = E.build_assessment("RoB2", "Good 2020", "u1", LOW_SIG)
    assert all(d.judgement == "low" for d in low.domains)


def test_high_study_has_high_domain():
    high = E.build_assessment("RoB2", "Bad 2019", "u2", HIGH_SIG)
    assert any(d.judgement == "high" for d in high.domains)


def test_build_assessment_fills_signalling_and_support():
    a = E.build_assessment("RoB2", "Good 2020", "u1", LOW_SIG)
    assert isinstance(a, RoBAssessment)
    assert len(a.domains) == 5
    for d in a.domains:
        assert d.signalling_answers, "signalling_answers must be populated"
        assert d.support_for_judgement, "support_for_judgement must be populated"
        # Every signalling question for the domain is recorded.
        assert len(d.signalling_answers) >= len(
            T.questions_for("RoB2", d.name))
        assert d.judgement in ("low", "some concerns", "high")


def test_missing_answers_treated_as_no_information():
    # Empty input must not crash and must produce a complete assessment.
    a = E.build_assessment("RoB2", "Sparse", "u9", {})
    assert len(a.domains) == 5
    assert a.overall in ("low", "some concerns", "high")
    # Every recorded answer is "No information".
    vals = {v for d in a.domains for v in d.signalling_answers.values()}
    assert vals == {T.NO_INFO}


def test_robins_i_native_levels_in_support():
    sig = {"Confounding": {"1.1": "Yes", "1.4": "No"}}  # potential + uncontrolled
    a = E.build_assessment("ROBINS-I", "Cohort 2018", "u4", sig)
    assert a.tool == "ROBINS-I"
    # serious/critical native level maps to stored 'high'.
    conf = next(d for d in a.domains if d.name == "Confounding")
    assert conf.judgement == "high"
    assert "native" in conf.support_for_judgement.lower()


def test_derive_overall_rules():
    assert E.derive_overall("RoB2", ["low", "low", "low", "low", "low"]) == "low"
    assert E.derive_overall("RoB2", ["low", "high", "low"]) == "high"
    # Three 'some concerns' lowers confidence to overall high under RoB2.
    assert E.derive_overall(
        "RoB2", ["some concerns"] * 3 + ["low"]) == "high"
    assert E.derive_overall("RoB2", ["some concerns", "low"]) == "some concerns"
    # ROBINS uses the worst-domain rule.
    assert E.derive_overall("ROBINS-I", ["low", "some concerns"]) == "some concerns"


# ── Agent ────────────────────────────────────────────────────────────────────
def _agent(tool: str = "RoB2") -> RiskOfBiasAssessor:
    prot = ReviewProtocol(title="t", risk_of_bias=RoBConfig(tool=tool))
    return RiskOfBiasAssessor(MockProvider(), prot)


def test_agent_assess_returns_complete_assessment():
    ag = _agent("RoB2")
    rec = Record(source="x", title="A randomized trial",
                 abstract="Randomized double-blind trial of X versus sham.")
    ex = ExtractionRecord(uid=rec.uid, study_label="Smith 2021",
                          design="randomized controlled trial")
    a = ag.assess(rec, ex, full_text="Participants randomly allocated. " * 40)
    assert a.uid == rec.uid and a.tool == "RoB2"
    assert len(a.domains) == 5
    assert a.overall in ("low", "some concerns", "high")
    for d in a.domains:
        assert d.signalling_answers


class _BoomProvider(MockProvider):
    def complete_json(self, **kwargs):
        raise RuntimeError("model unavailable")


def test_agent_fallback_is_varied_not_flat():
    prot = ReviewProtocol(title="t", risk_of_bias=RoBConfig(tool="RoB2"))
    ag = RiskOfBiasAssessor(_BoomProvider(), prot)
    rec = Record(source="x", title="Observational cohort",
                 abstract="A cohort study.")
    ex = ExtractionRecord(uid=rec.uid, study_label="Jones 2017",
                          design="prospective cohort")
    a = ag.assess(rec, ex)
    # Fallback still yields a complete, NON-flat assessment.
    assert len(a.domains) == 5
    judgements = {d.judgement for d in a.domains}
    assert len(judgements) >= 2, "fallback must not be uniform"
    for d in a.domains:
        assert d.support_for_judgement


# ── Figures ──────────────────────────────────────────────────────────────────
def _assessments():
    return [
        E.build_assessment("RoB2", "Good 2020", "u1", LOW_SIG),
        E.build_assessment("RoB2", "Bad 2019", "u2", HIGH_SIG),
        E.build_assessment("RoB2", "Mid 2021", "u3", MID_SIG),
    ]


def test_save_rob_figures_writes_valid_pdfs(tmp_path):
    paths = P.save_rob_figures(_assessments(), tmp_path)
    assert set(paths) == {"traffic", "summary"}
    pdfs = [p for ps in paths.values() for p in ps if p.suffix == ".pdf"]
    assert len(pdfs) == 2
    for p in pdfs:
        assert p.exists()
        with open(p, "rb") as fh:
            assert fh.read(5).startswith(b"%PDF"), f"{p} is not a valid PDF"
    # PNGs are also produced and valid.
    pngs = [p for ps in paths.values() for p in ps if p.suffix == ".png"]
    assert len(pngs) == 2
    for p in pngs:
        with open(p, "rb") as fh:
            assert fh.read(8) == b"\x89PNG\r\n\x1a\n"


def test_save_rob_figures_tolerates_empty(tmp_path):
    assert P.save_rob_figures([], tmp_path) == {}


def test_traffic_and_summary_figures_build():
    fig1 = P.build_rob_traffic_figure(_assessments())
    fig2 = P.build_rob_summary_figure(_assessments())
    # One extra column for Overall.
    assert fig1 is not None and fig2 is not None
    import matplotlib.pyplot as plt
    plt.close(fig1)
    plt.close(fig2)


def test_select_tool_for_design_matches_instrument():
    from neuroaion.rob_tools import select_tool_for_design as sel
    assert sel("randomized controlled trial") == "RoB2"
    assert sel("diagnostic accuracy study") == "QUADAS-2"
    assert sel("prospective cohort study") == "Newcastle-Ottawa"
    assert sel("non-randomized interventional study") == "ROBINS-I"
    assert sel("", "exposure") == "ROBINS-E"
    assert sel("quasi-experimental before-after") == "ROBINS-I"
    assert sel("") == "RoB2"        # safe default


def test_auto_tool_selection_uses_design(monkeypatch):
    from neuroaion.agents.rob import RiskOfBiasAssessor
    from neuroaion.llm import MockProvider
    from neuroaion.models import ExtractionRecord, Record, ReviewProtocol, RoBConfig
    prot = ReviewProtocol(title="t", risk_of_bias=RoBConfig(tool="auto"))
    agent = RiskOfBiasAssessor(MockProvider(), prot)
    rec = Record(source="s", doi="10/x", title="A diagnostic study")
    ex = ExtractionRecord(uid=rec.uid, study_label="Dx 2020", design="diagnostic accuracy study")
    a = agent.assess(rec, ex, full_text="Index test vs reference standard.")
    assert a.tool == "QUADAS-2"
