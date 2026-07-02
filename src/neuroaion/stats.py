"""Quantitative synthesis primitives (PRISMA items 13–14).

Journal-grade meta-analysis computed deterministically in Python — the language
model is never asked to produce a pooled estimate or a heterogeneity statistic.

Supports SMD (Hedges g), MD, log-OR/RR/HR, correlation (Fisher z) and proportion
(logit) measures; DerSimonian–Laird and REML τ² estimators; an optional
Hartung–Knapp–Sidik–Jonkman variance adjustment; Q/I²/τ/H with CIs; a 95 %
prediction interval; subgroup analysis (between-group Q); leave-one-out and
cumulative sensitivity; and publication-bias diagnostics (Egger, Begg,
trim-and-fill). Formulas follow the Cochrane Handbook (Ch. 10), Higgins &
Thompson (2002), and Viechtbauer's metafor conventions.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
from scipy import stats as scipy_stats
from scipy.special import gammaln

from .models import EffectEstimate, MetaAnalysisResult

RATIO = {"OR", "RR", "HR", "IRR", "ROM"}


# ── effect-measure conversion helpers (raw data → yi, var) ───────────────────
def hedges_g(mean_t, sd_t, n_t, mean_c, sd_c, n_c):
    df = n_t + n_c - 2
    sp = math.sqrt(((n_t - 1) * sd_t ** 2 + (n_c - 1) * sd_c ** 2) / df)
    d = (mean_t - mean_c) / sp
    J = math.exp(gammaln(df / 2.0) - math.log(math.sqrt(df / 2.0)) - gammaln((df - 1.0) / 2.0))
    g = J * d
    var_g = J ** 2 * ((n_t + n_c) / (n_t * n_c) + d ** 2 / (2.0 * df))
    return float(g), float(var_g)


def mean_difference(mean_t, sd_t, n_t, mean_c, sd_c, n_c):
    return float(mean_t - mean_c), float(sd_t ** 2 / n_t + sd_c ** 2 / n_c)


def log_or(a, b, c, d):
    if min(a, b, c, d) == 0:
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    return float(math.log((a * d) / (b * c))), float(1 / a + 1 / b + 1 / c + 1 / d)


def fisher_z(r, n):
    r = max(min(r, 0.999999), -0.999999)
    return float(math.atanh(r)), float(1.0 / (n - 3))


def logit_prop(events, n):
    e = events + 0.5 if events in (0, n) else events
    nn = n + 1 if events in (0, n) else n
    p = e / nn
    return float(math.log(p / (1 - p))), float(1.0 / (nn * p) + 1.0 / (nn * (1 - p)))


def _backtransform(measure: str):
    m = (measure or "").upper()
    if m in RATIO:
        return math.exp
    if m in {"COR", "R"}:
        return math.tanh
    if m in {"PROP", "PROPORTION"}:
        return lambda x: 1.0 / (1.0 + math.exp(-x))
    return lambda x: x


# ── _usable: the single on-analysis-scale extractor (effect, se) ─────────────
def _se_from_ci(lo: float, hi: float) -> float:
    return (hi - lo) / (2 * 1.959963985)


def _usable(e: EffectEstimate) -> Optional[tuple[float, float]]:
    if e.estimate is None:
        return None
    est, se = float(e.estimate), e.se
    ratio = e.measure.upper() in RATIO
    if se is None and e.ci_lower is not None and e.ci_upper is not None:
        if ratio:
            if e.ci_lower <= 0 or e.ci_upper <= 0 or est <= 0:
                return None
            return math.log(est), _se_from_ci(math.log(e.ci_lower), math.log(e.ci_upper))
        se = _se_from_ci(e.ci_lower, e.ci_upper)
    if se is None or se <= 0:
        return None
    if ratio:
        return (math.log(est), se) if est > 0 else None
    return est, se


# ── τ² estimators ────────────────────────────────────────────────────────────
def tau2_DL(ys, vs) -> float:
    ys, vs = np.asarray(ys, float), np.asarray(vs, float)
    w = 1.0 / vs
    mu = np.sum(w * ys) / np.sum(w)
    Q = float(np.sum(w * (ys - mu) ** 2))
    df = len(ys) - 1
    C = float(np.sum(w) - np.sum(w ** 2) / np.sum(w))
    return max(0.0, (Q - df) / C) if C > 0 else 0.0


def tau2_REML(ys, vs, tol=1e-7, max_iter=200) -> float:
    ys, vs = np.asarray(ys, float), np.asarray(vs, float)
    tau2 = max(tau2_DL(ys, vs), 0.0)
    for _ in range(max_iter):
        w = 1.0 / (vs + tau2)
        sw = np.sum(w)
        mu = np.sum(w * ys) / sw
        # REML estimating equation (Viechtbauer 2005): the estimated-mean
        # correction 1/Σw is an additive term, NOT divided by Σw².
        new = max(0.0, float(np.sum(w ** 2 * ((ys - mu) ** 2 - vs)) / np.sum(w ** 2) + 1.0 / sw))
        if abs(new - tau2) < tol:
            return new
        tau2 = new
    return tau2


def _pool(ys, vs, *, model="random", tau2_method="DL", knha=False) -> dict:
    ys, vs = np.asarray(ys, float), np.asarray(vs, float)
    k = len(ys)
    df = k - 1
    tau2 = (tau2_REML(ys, vs) if tau2_method.upper() == "REML" else tau2_DL(ys, vs)) \
        if model == "random" else 0.0
    w = 1.0 / (vs + tau2)
    mu = float(np.sum(w * ys) / np.sum(w))
    se = float(math.sqrt(1.0 / np.sum(w)))
    w_fe = 1.0 / vs
    mu_fe = float(np.sum(w_fe * ys) / np.sum(w_fe))
    Q = float(np.sum(w_fe * (ys - mu_fe) ** 2))
    if knha and k >= 2 and df > 0:
        q_hk = float(np.sum(w * (ys - mu) ** 2) / df)
        se = math.sqrt(q_hk / np.sum(w))
        # Röver-Knapp-Friede ad-hoc floor: never report a Hartung-Knapp SE narrower
        # than the classical (Wald) random-effects SE — avoids anticonservative
        # intervals when tau^2 ~ 0 and k is small.
        se = max(se, math.sqrt(1.0 / np.sum(w)))
        crit = float(scipy_stats.t.ppf(0.975, df))
        stat = mu / se if se else 0.0
        p = float(2 * scipy_stats.t.sf(abs(stat), df))
        dist, dist_df = "t", df
    else:
        crit, dist, dist_df = 1.959963985, "z", None
        stat = mu / se if se else 0.0
        p = float(2 * scipy_stats.norm.sf(abs(stat)))
    return dict(estimate=mu, se=se, ci_lower=mu - crit * se, ci_upper=mu + crit * se,
                p_value=p, test_stat=stat, test_dist=dist, df=dist_df,
                tau2=tau2, Q=Q, Q_df=df)


def _heterogeneity(Q, df, k) -> dict:
    q_p = float(scipy_stats.chi2.sf(Q, df)) if df > 0 else None
    H = float(math.sqrt(max(Q / df, 1.0))) if df > 0 else 1.0
    I2 = max(0.0, (Q - df) / Q) * 100 if Q > 0 else 0.0
    i2_lo = i2_hi = None
    if df > 0 and Q > 0:
        if Q > k:
            se_lnH = 0.5 * (math.log(Q) - math.log(df)) / (math.sqrt(2 * Q) - math.sqrt(2 * df - 1))
        elif df > 1:
            se_lnH = math.sqrt(1.0 / (2 * (df - 1)) * (1 - 1.0 / (3 * (df - 1) ** 2)))
        else:
            se_lnH = None
        if se_lnH:
            lnH = math.log(H)
            h_lo, h_hi = math.exp(max(0.0, lnH - 1.96 * se_lnH)), math.exp(lnH + 1.96 * se_lnH)
            i2_lo = max(0.0, (h_lo ** 2 - 1) / h_lo ** 2) * 100
            i2_hi = min(100.0, (h_hi ** 2 - 1) / h_hi ** 2) * 100
    return dict(q_p_value=q_p, H=H, I2=I2, i2_ci_lower=i2_lo, i2_ci_upper=i2_hi)


def prediction_interval(mu, se_re, tau2, k):
    if k < 3 or tau2 is None:
        return None, None
    crit = float(scipy_stats.t.ppf(0.975, k - 2))
    spread = crit * math.sqrt(tau2 + se_re ** 2)
    return mu - spread, mu + spread


def subgroup_analysis(ys, vs, groups, *, model="random", tau2_method="DL", knha=False, bt=lambda x: x):
    ys, vs = np.asarray(ys, float), np.asarray(vs, float)
    groups = list(groups)
    levels = [g for g in dict.fromkeys(groups) if g is not None]
    rows, mus, vbs = [], [], []
    for g in levels:
        idx = [i for i, gg in enumerate(groups) if gg == g]
        if not idx:
            continue
        r = _pool(ys[idx], vs[idx], model=model, tau2_method=tau2_method, knha=knha)
        het = _heterogeneity(r["Q"], r["Q_df"], len(idx))
        rows.append({"subgroup": str(g), "k": len(idx),
                     "estimate": round(bt(r["estimate"]), 4),
                     "ci_lower": round(bt(r["ci_lower"]), 4),
                     "ci_upper": round(bt(r["ci_upper"]), 4),
                     "i_squared": round(het["I2"], 1)})
        mus.append(r["estimate"])
        vbs.append(r["se"] ** 2)
    Qb = dfb = Qb_p = None
    if len(mus) >= 2:
        mus, vbs = np.asarray(mus), np.asarray(vbs)
        wb = 1.0 / vbs
        grand = np.sum(wb * mus) / np.sum(wb)
        Qb = float(np.sum(wb * (mus - grand) ** 2))
        dfb = len(mus) - 1
        Qb_p = float(scipy_stats.chi2.sf(Qb, dfb))
    return {"subgroups": rows, "q_between": Qb, "q_between_df": dfb, "q_between_p": Qb_p}


def leave_one_out(ys, vs, labels, *, model="random", tau2_method="DL", knha=False, bt=lambda x: x):
    ys, vs = np.asarray(ys, float), np.asarray(vs, float)
    out = []
    for i in range(len(ys)):
        idx = [j for j in range(len(ys)) if j != i]
        if not idx:
            continue
        r = _pool(ys[idx], vs[idx], model=model, tau2_method=tau2_method, knha=knha)
        het = _heterogeneity(r["Q"], r["Q_df"], len(idx))
        out.append({"omitted": labels[i], "estimate": round(bt(r["estimate"]), 4),
                    "ci_lower": round(bt(r["ci_lower"]), 4),
                    "ci_upper": round(bt(r["ci_upper"]), 4),
                    "i_squared": round(het["I2"], 1)})
    return out


def begg_test(ys, vs):
    ys, vs = np.asarray(ys, float), np.asarray(vs, float)
    if len(ys) < 3:
        return None
    w = 1.0 / vs
    mu = np.sum(w * ys) / np.sum(w)
    v_star = np.where(vs - 1.0 / np.sum(w) <= 0, np.finfo(float).tiny, vs - 1.0 / np.sum(w))
    tau, p = scipy_stats.kendalltau((ys - mu) / np.sqrt(v_star), vs)
    return {"tau": float(tau), "p": float(p)}


def trim_and_fill(ys, vs, *, model="random", tau2_method="DL", max_iter=100):
    ys, vs = np.asarray(ys, float), np.asarray(vs, float)
    k = len(ys)
    if k < 3:
        return None
    mu0 = _pool(ys, vs, model=model, tau2_method=tau2_method)["estimate"]
    side = "left" if mu0 > np.median(ys) else "right"
    yy = ys.copy() if side == "right" else -ys.copy()
    L, L_prev, it = 0, -1, 0
    mu = mu0 if side == "right" else -mu0
    while L != L_prev and it < max_iter:
        it += 1
        L_prev = L
        order = np.argsort(yy)[: k - L]
        mu = _pool(yy[order], vs[order], model="fixed")["estimate"]
        centered = yy - mu
        ranks = scipy_stats.rankdata(np.abs(centered))
        Tn = float(np.sum(ranks[np.sign(centered) > 0]))
        L = max(0, int(round((4 * Tn - k * (k + 1)) / (2 * k - 1))))
    if L > 0:
        mu = _pool(yy, vs, model=model, tau2_method=tau2_method)["estimate"]
        imp = np.argsort(yy)[::-1][:L]
        yy_full = np.concatenate([yy, 2 * mu - yy[imp]])
        vv_full = np.concatenate([vs, vs[imp]])
        adj = _pool(yy_full, vv_full, model=model, tau2_method=tau2_method)["estimate"]
    else:
        adj = mu
    adj = adj if side == "right" else -adj
    return {"missing": int(L), "side": side, "adjusted_estimate": float(adj)}


# ── main entry point ─────────────────────────────────────────────────────────
def meta_analyze(effects, *, measure="SMD", model="random", labels=None,
                 tau2_method="REML", knha=False, prediction_interval_=True,
                 subgroup=False, leave_one_out_=False, publication_bias=False,
                 outcome="") -> Optional[MetaAnalysisResult]:
    labels = labels or [f"study {i+1}" for i in range(len(effects))]
    rows, used, groups = [], [], []
    for lab, e in zip(labels, effects):
        u = _usable(e)
        if u is not None:
            rows.append(u)
            used.append(lab)
            groups.append(getattr(e, "subgroup", None))
    k = len(rows)
    if k == 0:
        return None
    ys = [r[0] for r in rows]
    vs = [r[1] ** 2 for r in rows]
    bt = _backtransform(measure)
    log_scale = measure.upper() in RATIO

    res = _pool(ys, vs, model=model, tau2_method=tau2_method, knha=knha)
    het = _heterogeneity(res["Q"], res["Q_df"], k)
    se_re = float(math.sqrt(1.0 / np.sum(1.0 / (np.asarray(vs) + res["tau2"]))))

    forest = []
    wsum = sum(1.0 / s for s in vs)
    for lab, (y, se) in zip(used, rows):
        lo, hi = y - 1.96 * se, y + 1.96 * se
        forest.append({"study": lab,
                       "estimate": round(math.exp(y) if log_scale else y, 4),
                       "ci_lower": round(math.exp(lo) if log_scale else lo, 4),
                       "ci_upper": round(math.exp(hi) if log_scale else hi, 4),
                       "weight_pct": round(100 * (1.0 / se ** 2) / wsum, 1)})

    out = MetaAnalysisResult(
        measure=measure, model=model, k_studies=k, outcome=outcome,
        tau2_method=tau2_method, knha=knha,
        pooled_estimate=round(bt(res["estimate"]), 4),
        ci_lower=round(bt(res["ci_lower"]), 4), ci_upper=round(bt(res["ci_upper"]), 4),
        se_pooled=round(res["se"], 4), p_value=round(res["p_value"], 5),
        test_stat=round(res["test_stat"], 4), test_dist=res["test_dist"], df=res["df"],
        q_statistic=round(res["Q"], 3), q_p_value=(round(het["q_p_value"], 5) if het["q_p_value"] is not None else None),
        i_squared=round(het["I2"], 1),
        i_squared_ci_lower=(round(het["i2_ci_lower"], 1) if het["i2_ci_lower"] is not None else None),
        i_squared_ci_upper=(round(het["i2_ci_upper"], 1) if het["i2_ci_upper"] is not None else None),
        tau_squared=round(res["tau2"], 4), tau=round(math.sqrt(res["tau2"]), 4),
        H=round(het["H"], 3), forest=forest)

    if prediction_interval_ and model == "random":
        pl, pu = prediction_interval(res["estimate"], se_re, res["tau2"], k)
        if pl is not None:
            out.pi_lower = round(bt(pl), 4)
            out.pi_upper = round(bt(pu), 4)
    if subgroup and any(g is not None for g in groups):
        sg = subgroup_analysis(ys, vs, groups, model=model, tau2_method=tau2_method, knha=knha, bt=bt)
        out.subgroups, out.q_between = sg["subgroups"], sg["q_between"]
        out.q_between_df, out.q_between_p = sg["q_between_df"], sg["q_between_p"]
    if leave_one_out_ and k >= 3:
        out.leave_one_out = leave_one_out(ys, vs, used, model=model, tau2_method=tau2_method, knha=knha, bt=bt)
    if publication_bias and k >= 3:
        eg = eggers_test(effects)
        if eg:
            out.eggers_intercept, out.eggers_p, out.eggers_k = eg["intercept"], eg["p"], eg["k"]
        bg = begg_test(ys, vs)
        if bg:
            out.begg_tau, out.begg_p = round(bg["tau"], 4), round(bg["p"], 4)
        tf = trim_and_fill(ys, vs, model=model, tau2_method=tau2_method)
        if tf:
            out.trimfill_missing, out.trimfill_side = tf["missing"], tf["side"]
            out.trimfill_adjusted_estimate = round(bt(tf["adjusted_estimate"]), 4)
        out.funnel = funnel_points(effects, measure)
    return out


def cohen_kappa(a: list[str], b: list[str]) -> Optional[float]:
    """Cohen's kappa for two reviewers' categorical decisions over the same items."""
    if not a or len(a) != len(b):
        return None
    cats = sorted(set(a) | set(b))
    idx = {c: i for i, c in enumerate(cats)}
    n = len(a)
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    pa, pb = [0.0] * len(cats), [0.0] * len(cats)
    for x, y in zip(a, b):
        pa[idx[x]] += 1 / n
        pb[idx[y]] += 1 / n
    expected = sum(pa[i] * pb[i] for i in range(len(cats)))
    if expected >= 1.0:
        return 1.0
    return round((observed - expected) / (1 - expected), 3)


def funnel_points(effects: list[EffectEstimate], measure: str = "SMD") -> list[dict]:
    """Per-study (effect, se) pairs for a funnel plot, on the analysis scale."""
    out = []
    log_scale = measure.upper() in RATIO
    for e in effects:
        u = _usable(e)
        if u is not None:
            y, se = u
            out.append({"estimate": round(math.exp(y) if log_scale else y, 4), "se": round(se, 4)})
    return out


def eggers_test(effects: list[EffectEstimate]) -> Optional[dict]:
    """Egger's regression test for small-study effects / funnel asymmetry."""
    pts = [u for u in (_usable(e) for e in effects) if u is not None]
    if len(pts) < 3:
        return None
    y = np.array([p[0] for p in pts], dtype=float)
    se = np.array([p[1] for p in pts], dtype=float)
    snd, precision = y / se, 1.0 / se
    n = len(pts)
    X = np.column_stack([np.ones(n), precision])
    beta, *_ = np.linalg.lstsq(X, snd, rcond=None)
    resid = snd - X @ beta
    dof = n - 2
    if dof <= 0:
        return None
    sigma2 = float(resid @ resid) / dof
    try:
        cov = sigma2 * np.linalg.inv(X.T @ X)
    except np.linalg.LinAlgError:
        return None
    se_int = math.sqrt(max(cov[0, 0], 0.0))
    if se_int == 0:
        return None
    t = beta[0] / se_int
    p = float(2 * (1 - scipy_stats.t.cdf(abs(t), dof)))
    return {"intercept": round(float(beta[0]), 4), "p": round(p, 4), "k": n, "underpowered": n < 10}
