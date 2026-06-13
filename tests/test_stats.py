import math

from neuroaion.models import EffectEstimate
from neuroaion.stats import cohen_kappa, meta_analyze


def test_meta_analysis_pools_estimates():
    effects = [
        EffectEstimate(outcome="n-back", measure="SMD", estimate=0.5, se=0.2),
        EffectEstimate(outcome="n-back", measure="SMD", estimate=0.3, se=0.2),
        EffectEstimate(outcome="n-back", measure="SMD", estimate=0.4, se=0.25),
    ]
    res = meta_analyze(effects, measure="SMD", model="random")
    assert res is not None
    assert res.k_studies == 3
    # Pooled estimate must lie within the range of inputs.
    assert 0.3 <= res.pooled_estimate <= 0.5
    assert res.i_squared is not None
    assert 0 <= res.i_squared <= 100


def test_meta_analysis_log_scale_for_ratios():
    # Two odds ratios; pooled OR should be positive and between the inputs.
    effects = [
        EffectEstimate(measure="OR", estimate=2.0, ci_lower=1.2, ci_upper=3.3),
        EffectEstimate(measure="OR", estimate=1.5, ci_lower=1.0, ci_upper=2.25),
    ]
    res = meta_analyze(effects, measure="OR", model="fixed")
    assert res is not None
    assert 1.5 <= res.pooled_estimate <= 2.0


def test_meta_analysis_needs_usable_data():
    assert meta_analyze([EffectEstimate(estimate=None)], measure="SMD") is None


def test_cohen_kappa_perfect_and_chance():
    assert cohen_kappa(["a", "b", "a"], ["a", "b", "a"]) == 1.0
    k = cohen_kappa(["a", "b", "a", "b"], ["b", "a", "b", "a"])
    assert k is not None and k < 0  # systematic disagreement
