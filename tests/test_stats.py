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


def test_eggers_and_funnel():
    from neuroaion.models import EffectEstimate
    from neuroaion.stats import eggers_test, funnel_points

    # Asymmetric: small (imprecise) studies have larger effects → asymmetry.
    asym = [
        EffectEstimate(estimate=0.2, se=0.05),
        EffectEstimate(estimate=0.3, se=0.10),
        EffectEstimate(estimate=0.6, se=0.30),
        EffectEstimate(estimate=0.9, se=0.45),
        EffectEstimate(estimate=1.2, se=0.60),
    ]
    res = eggers_test(asym)
    assert res is not None
    assert res["k"] == 5 and res["underpowered"] is True
    assert "intercept" in res and "p" in res

    assert funnel_points(asym, "SMD")[0]["se"] == 0.05
    # Fewer than three usable studies → no test.
    assert eggers_test(asym[:2]) is None


# ── journal-grade additions ──────────────────────────────────────────────────
def _smd_set():
    return [
        EffectEstimate(measure="SMD", estimate=0.8, se=0.20, subgroup="anodal"),
        EffectEstimate(measure="SMD", estimate=0.6, se=0.18, subgroup="anodal"),
        EffectEstimate(measure="SMD", estimate=0.9, se=0.22, subgroup="anodal"),
        EffectEstimate(measure="SMD", estimate=0.2, se=0.15, subgroup="cathodal"),
        EffectEstimate(measure="SMD", estimate=0.1, se=0.17, subgroup="cathodal"),
        EffectEstimate(measure="SMD", estimate=0.3, se=0.19, subgroup="cathodal"),
    ]


def test_prediction_interval_contains_confidence_interval():
    res = meta_analyze(_smd_set(), measure="SMD", model="random",
                       tau2_method="REML", prediction_interval_=True)
    assert res.pi_lower is not None and res.pi_upper is not None
    # A 95% PI is always at least as wide as the 95% CI of the mean.
    assert res.pi_lower <= res.ci_lower
    assert res.pi_upper >= res.ci_upper


def test_hksj_widens_interval_under_heterogeneity():
    base = meta_analyze(_smd_set(), measure="SMD", model="random", knha=False)
    hk = meta_analyze(_smd_set(), measure="SMD", model="random", knha=True)
    assert hk.test_dist == "t" and base.test_dist == "z"
    assert (hk.ci_upper - hk.ci_lower) > (base.ci_upper - base.ci_lower)


def test_reml_and_dl_both_nonnegative():
    dl = meta_analyze(_smd_set(), measure="SMD", model="random", tau2_method="DL")
    reml = meta_analyze(_smd_set(), measure="SMD", model="random", tau2_method="REML")
    assert dl.tau_squared >= 0 and reml.tau_squared >= 0
    assert dl.tau2_method == "DL" and reml.tau2_method == "REML"
    # H and I² CI are reported.
    assert dl.H is not None and dl.tau is not None


def test_subgroup_between_group_q():
    res = meta_analyze(_smd_set(), measure="SMD", model="random", subgroup=True)
    assert len(res.subgroups) == 2
    labels = {s["subgroup"] for s in res.subgroups}
    assert labels == {"anodal", "cathodal"}
    assert res.q_between is not None and res.q_between >= 0
    assert res.q_between_df == 1 and res.q_between_p is not None


def test_leave_one_out_has_k_rows():
    effs = _smd_set()
    res = meta_analyze(effs, measure="SMD", model="random", leave_one_out_=True)
    assert len(res.leave_one_out) == len(effs)
    for row in res.leave_one_out:
        assert "omitted" in row and "estimate" in row


def test_publication_bias_suite():
    res = meta_analyze(_smd_set(), measure="SMD", model="random",
                       publication_bias=True)
    assert res.eggers_p is not None and res.eggers_k == 6
    assert res.begg_tau is not None and res.begg_p is not None
    assert res.trimfill_missing is not None and res.trimfill_side in {"left", "right"}
    assert len(res.funnel) == 6


def test_hedges_g_and_log_or_conversions():
    from neuroaion.stats import hedges_g, log_or, mean_difference, fisher_z
    g, var = hedges_g(2.0, 1.0, 30, 1.0, 1.0, 30)
    assert g > 0 and var > 0
    lor, vlor = log_or(20, 10, 12, 18)
    assert lor > 0 and vlor > 0
    md, vmd = mean_difference(5.0, 2.0, 25, 3.0, 2.0, 25)
    assert md == 2.0 and vmd > 0
    z, vz = fisher_z(0.5, 40)
    assert z > 0 and vz == 1.0 / 37


def test_nonfinite_inputs_are_dropped_not_pooled():
    import math
    from neuroaion.models import EffectEstimate
    from neuroaion.stats import meta_analyze
    effs = [
        EffectEstimate(measure="SMD", estimate=0.5, se=0.2),
        EffectEstimate(measure="SMD", estimate=float("nan"), se=0.2),
        EffectEstimate(measure="SMD", estimate=0.4, se=float("inf")),
        EffectEstimate(measure="SMD", estimate=0.6, se=0.25),
    ]
    m = meta_analyze(effs, measure="SMD", model="fixed")
    # Only the two finite studies are counted and pooled.
    assert m.k_studies == 2 and math.isfinite(m.pooled_estimate)


def test_unsupported_measure_refused():
    from neuroaion.models import EffectEstimate
    from neuroaion.stats import meta_analyze
    effs = [EffectEstimate(measure="DTA", estimate=0.9, se=0.05),
            EffectEstimate(measure="DTA", estimate=0.85, se=0.05)]
    assert meta_analyze(effs, measure="DTA") is None


def test_proportion_pooled_on_logit_scale():
    import math
    from neuroaion.models import EffectEstimate
    from neuroaion.stats import meta_analyze
    effs = [EffectEstimate(measure="PROP", estimate=0.30, se=0.02),
            EffectEstimate(measure="PROP", estimate=0.25, se=0.02)]
    m = meta_analyze(effs, measure="PROP", model="fixed")
    assert 0.24 < m.pooled_estimate < 0.31          # sensible, between the inputs
    assert 0.0 < m.ci_lower and m.ci_upper < 1.0    # CI stays in range
