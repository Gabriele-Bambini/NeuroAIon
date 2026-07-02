"""Non-intervention review types are not forced into meta-analysis / RoB / GRADE."""
from neuroaion.agents.synthesis import EvidenceSynthesizer
from neuroaion.llm import MockProvider
from neuroaion.models import (EffectEstimate, ExtractionRecord, ReviewProtocol,
                              RoBConfig, SynthesisConfig)


def _extractions():
    return [
        ExtractionRecord(uid="a", study_label="A 2020", design="cohort",
                         effects=[EffectEstimate(outcome="prevalence", measure="PROP",
                                                 estimate=0.3, se=0.02)]),
        ExtractionRecord(uid="b", study_label="B 2021", design="cohort",
                         effects=[EffectEstimate(outcome="prevalence", measure="PROP",
                                                 estimate=0.25, se=0.02)]),
    ]


def test_scoping_review_skips_meta_and_grade():
    prot = ReviewProtocol(title="Scoping map", review_type="scoping",
                          synthesis=SynthesisConfig(effect_measure="PROP"))
    syn = EvidenceSynthesizer(MockProvider(), prot).synthesize(_extractions(), [])
    assert syn.meta_analysis is None and not syn.meta_analyses
    assert not syn.grade_table and not syn.grade_certainty


def test_grade_flag_off_suppresses_grade_but_keeps_meta():
    prot = ReviewProtocol(title="Effect", review_type="intervention",
                          synthesis=SynthesisConfig(effect_measure="PROP"),
                          risk_of_bias=RoBConfig(tool="RoB2", grade=False))
    syn = EvidenceSynthesizer(MockProvider(), prot).synthesize(_extractions(), [])
    assert syn.meta_analysis is not None            # still pooled
    assert not syn.grade_table                       # but no GRADE table


def test_prevalence_review_pools_but_no_grade():
    prot = ReviewProtocol(title="Prevalence", review_type="prevalence",
                          synthesis=SynthesisConfig(effect_measure="PROP"))
    syn = EvidenceSynthesizer(MockProvider(), prot).synthesize(_extractions(), [])
    assert syn.meta_analysis is not None
    assert not syn.grade_table
