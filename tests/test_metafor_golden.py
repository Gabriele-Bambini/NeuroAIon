"""Numerical equivalence with R `metafor` on canonical datasets — the proof the
meta-analysis is *correct*, not merely internally consistent.

Expected values are from a single authoritative `metafor::rma()` run on the
BCG-vaccine dataset (Colditz 1994; `metafor::dat.bcg`), log-risk-ratio.
"""
import math

from neuroaion.models import EffectEstimate
from neuroaion.stats import meta_analyze, hedges_g, log_or

# dat.bcg: tpos, tneg, cpos, cneg (13 trials)
BCG = [(4, 119, 11, 128), (6, 300, 29, 274), (3, 228, 11, 209),
       (62, 13536, 248, 12619), (33, 5036, 47, 5761), (180, 1361, 372, 1079),
       (8, 2537, 10, 619), (505, 87886, 499, 87892), (29, 7470, 45, 7232),
       (17, 1699, 65, 1600), (186, 50448, 141, 27197), (5, 2493, 3, 2338),
       (27, 16886, 29, 17825)]


def _bcg_effects():
    effs = []
    for tp, tn, cp, cn in BCG:
        rr = (tp / (tp + tn)) / (cp / (cp + cn))
        se = math.sqrt(1 / tp - 1 / (tp + tn) + 1 / cp - 1 / (cp + cn))
        effs.append(EffectEstimate(measure="RR", estimate=rr, se=se))
    return effs


def test_bcg_escalc_row1():
    # metafor::escalc(measure="RR", dat.bcg)[1]: yi = -0.8893, vi = 0.3256
    tp, tn, cp, cn = BCG[0]
    yi = math.log((tp / (tp + tn)) / (cp / (cp + cn)))
    vi = 1 / tp - 1 / (tp + tn) + 1 / cp - 1 / (cp + cn)
    assert abs(yi - (-0.8893)) < 1e-3
    assert abs(vi - 0.3256) < 1e-3


def test_bcg_reml_matches_metafor():
    # metafor rma(measure="RR", method="REML"): estimate -0.7141, ci [-1.0672,-0.3610],
    # tau^2 0.3132, I^2 92.12%, Q(12) 152.233 (p<1e-4).
    m = meta_analyze(_bcg_effects(), measure="RR", model="random", tau2_method="REML")
    logrr = math.log(m.pooled_estimate)
    lo, hi = math.log(m.ci_lower), math.log(m.ci_upper)
    assert abs(logrr - (-0.7141)) < 2e-3
    assert abs(lo - (-1.0672)) < 3e-3
    assert abs(hi - (-0.3610)) < 3e-3
    assert abs(m.tau_squared - 0.3132) < 2e-3
    assert abs(m.i_squared - 92.12) < 0.3
    assert abs(m.q_statistic - 152.233) < 0.1
    assert m.q_p_value is not None and m.q_p_value < 1e-4


def test_bcg_dl_tau2_matches_metafor():
    # DerSimonian-Laird tau^2 = 0.3088 (exact); estimate -0.7141.
    m = meta_analyze(_bcg_effects(), measure="RR", model="random", tau2_method="DL")
    assert abs(m.tau_squared - 0.3088) < 2e-3
    assert abs(math.log(m.pooled_estimate) - (-0.7141)) < 2e-3
    assert abs(m.q_statistic - 152.233) < 0.1


def test_bcg_hksj_widens_and_uses_t():
    base = meta_analyze(_bcg_effects(), measure="RR", model="random", tau2_method="REML")
    hk = meta_analyze(_bcg_effects(), measure="RR", model="random", tau2_method="REML", knha=True)
    assert hk.test_dist == "t" and hk.df == 12
    # Hartung-Knapp CI is wider than the Wald CI here.
    assert (math.log(hk.ci_upper) - math.log(hk.ci_lower)) > (math.log(base.ci_upper) - math.log(base.ci_lower))


def test_hedges_g_escalc_equivalence():
    # metafor escalc(measure="SMD"): g = J*d, J = exp(lgamma(m/2)-log(sqrt(m/2))-lgamma((m-1)/2)).
    g, v = hedges_g(5.0, 2.0, 20, 3.0, 2.0, 20)     # d = 1.0, df = 38
    m = 38
    J = math.exp(math.lgamma(m / 2) - math.log(math.sqrt(m / 2)) - math.lgamma((m - 1) / 2))
    d = 1.0
    exp_g = J * d
    exp_v = J ** 2 * ((40) / (400) + d ** 2 / (2 * m))
    assert abs(g - exp_g) < 1e-6
    assert abs(v - exp_v) < 1e-6


def test_log_or_2x2():
    # log-OR of a 2x2 with an exact hand value: a=20,b=10,c=12,d=18 -> OR=3.0, logOR=ln 3.
    y, v = log_or(20, 10, 12, 18)
    assert abs(y - math.log(3.0)) < 1e-9
    assert abs(v - (1 / 20 + 1 / 10 + 1 / 12 + 1 / 18)) < 1e-9
