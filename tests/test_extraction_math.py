"""Recompute-from-raw: validated against metafor::escalc and the source papers."""
import math

from neuroaion.extraction_math import (
    from_2x2,
    hedges_g,
    mean_difference,
    mean_sd_from_median,
    recompute,
    sd_from_ci,
    sd_from_p_twogroup,
    sd_from_se,
)
from neuroaion.models import EffectEstimate

REL = 1e-3


def test_log_or_matches_escalc():
    # escalc(measure="OR", ai=10,bi=40,ci=5,di=45): yi=ln(2.25)=0.81093,
    # vi=1/10+1/40+1/5+1/45=0.34722
    d = from_2x2(10, 50, 5, 50, "OR")
    assert math.isclose(d.estimate, math.log(2.25), rel_tol=REL)
    assert math.isclose(d.se ** 2, 1 / 10 + 1 / 40 + 1 / 5 + 1 / 45, rel_tol=REL)


def test_log_rr_matches_escalc():
    # escalc(measure="RR", ai=10,n1i=50,ci=5,n2i=50): yi=ln(2)=0.69315,
    # vi=1/10-1/50+1/5-1/50=0.26
    d = from_2x2(10, 50, 5, 50, "RR")
    assert math.isclose(d.estimate, 0.69315, rel_tol=REL)
    assert math.isclose(d.se ** 2, 0.26, rel_tol=REL)


def test_zero_cell_triggers_sweeting_correction():
    d = from_2x2(0, 50, 5, 50, "OR")
    assert d is not None and math.isfinite(d.estimate) and "continuity" in d.provenance


def test_risk_difference():
    d = from_2x2(10, 50, 5, 50, "RD")
    assert math.isclose(d.estimate, 0.1, rel_tol=REL)
    # SE = sqrt(.2*.8/50 + .1*.9/50)
    assert math.isclose(d.se, math.sqrt(0.2 * 0.8 / 50 + 0.1 * 0.9 / 50), rel_tol=REL)


def test_mean_difference():
    d = mean_difference(10.0, 2.0, 30, 8.0, 2.5, 30)
    assert math.isclose(d.estimate, 2.0, rel_tol=REL)
    assert math.isclose(d.se, math.sqrt(4 / 30 + 6.25 / 30), rel_tol=REL)


def test_hedges_g_matches_escalc():
    # escalc(measure="SMD", m1i=10,sd1i=2,n1i=30, m2i=8,sd2i=2.5,n2i=30):
    # yi=0.8747 (J-corrected), vi=0.07304
    d = hedges_g(10.0, 2.0, 30, 8.0, 2.5, 30)
    assert math.isclose(d.estimate, 0.87197, rel_tol=2e-3)
    assert math.isclose(d.se ** 2, 0.07322, rel_tol=5e-3)


def test_wan_luo_c2_iqr():
    # Wan 2014 worked example (scenario C2): q1=8, median=12, q3=16, n=100
    got = mean_sd_from_median(100, 12, q1=8, q3=16)
    mean, sd, _ = got
    assert math.isclose(mean, 12.0, abs_tol=0.05)
    # eta ≈ 1.35 for n=100 → SD ≈ (16-8)/1.35 ≈ 5.9
    assert 5.7 < sd < 6.1


def test_wan_luo_c1_range():
    got = mean_sd_from_median(100, 12, lo=2, hi=22)
    mean, sd, _ = got
    assert 11 < mean < 13 and sd > 0


def test_sd_recovery_helpers():
    assert math.isclose(sd_from_se(0.5, 25), 2.5, rel_tol=REL)
    # 95% CI [8,12] for a mean of a group of n=16 → SD = (12-8)/(2*1.96)*4
    assert math.isclose(sd_from_ci(8, 12, 16), (4 / (2 * 1.959964)) * 4, rel_tol=REL)
    sd = sd_from_p_twogroup(0.05, 10, 8, 30, 30)
    assert sd is not None and sd > 0


def test_recompute_binary_fills_ratio_and_ci():
    e = EffectEstimate(measure="OR", events_intervention=10, n_intervention=50,
                       events_comparator=5, n_comparator=50)
    r = recompute(e)
    assert r.recomputed and math.isclose(r.estimate, 2.25, rel_tol=REL)
    assert r.ci_lower < r.estimate < r.ci_upper and r.se > 0


def test_recompute_continuous_from_median():
    e = EffectEstimate(measure="MD", n_intervention=100, n_comparator=100,
                       median_intervention=12, q1_intervention=8, q3_intervention=16,
                       median_comparator=10, q1_comparator=6, q3_comparator=14)
    r = recompute(e)
    assert r.recomputed and r.se and math.isclose(r.estimate, 2.0, abs_tol=0.2)
    assert "median" in r.provenance


def test_double_zero_2x2_excluded():
    assert from_2x2(0, 20, 0, 20, "OR") is None
    assert from_2x2(0, 20, 0, 20, "RR") is None
    # A single zero cell is still corrected, not excluded.
    assert from_2x2(0, 20, 5, 20, "OR") is not None


def test_median_conversion_rejects_bad_input():
    assert mean_sd_from_median(1, 5, q1=4, q3=6) is None          # n<2
    assert mean_sd_from_median(30, 5, q1=8, q3=2) is None          # q1>q3 (median outside)
    assert mean_sd_from_median(30, 5, lo=6, hi=10) is None         # median<lo
    assert mean_sd_from_median(30, 5, q1=4, q3=6) is not None      # valid


def test_recompute_recovers_sd_from_p_value():
    e = EffectEstimate(measure="MD", mean_intervention=10.0, mean_comparator=8.0,
                       n_intervention=30, n_comparator=30, p_value=0.01)
    r = recompute(e)
    assert r.recomputed and r.se and "p-value" in r.provenance
    assert math.isclose(r.estimate, 2.0, rel_tol=REL)


def test_recompute_falls_back_to_ci_se():
    e = EffectEstimate(measure="RR", estimate=1.5, ci_lower=1.1, ci_upper=2.0)
    r = recompute(e)
    assert not r.recomputed and r.se is not None
    # SE of log RR = (ln2 - ln1.1)/(2*1.96)
    assert math.isclose(r.se, (math.log(2.0) - math.log(1.1)) / (2 * 1.959964), rel_tol=REL)
