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


def _analysis_scale(measure: str) -> str:
    """The scale on which a measure is *pooled* (may differ from how it is reported).

    Ratios pool on the log scale, proportions on the logit scale, correlations on
    Fisher's z. Everything else (MD, SMD, RD) pools as reported. Pooling a
    proportion or a correlation on its raw scale is a classic, silent error — the
    variance is not stabilised and the CI can leave [0,1] or [-1,1].
    """
    m = (measure or "").upper()
    if m in RATIO:
        return "log"
    if m in {"PROP", "PROPORTION"}:
        return "logit"
    if m in {"COR", "R"}:
        return "ztrans"
    return "identity"


def _backtransform(measure: str):
    scale = _analysis_scale(measure)
    if scale == "log":
        return math.exp
    if scale == "ztrans":
        return math.tanh
    if scale == "logit":
        return lambda x: 1.0 / (1.0 + math.exp(-x))
    return lambda x: x


# ── _usable: the single on-analysis-scale extractor (effect, se) ─────────────
def _se_from_ci(lo: float, hi: float) -> float:
    return (hi - lo) / (2 * 1.959963985)


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _usable(e: EffectEstimate) -> Optional[tuple[float, float]]:
    """Return (effect, se) transformed onto the measure's *analysis* scale.

    The reported estimate/CI/SE are converted to the pooling scale (log for
    ratios, logit for proportions, Fisher-z for correlations) so the pool, its
    CI and every sensitivity analysis operate on the variance-stabilised scale;
    the forest and pooled point are back-transformed for display via
    ``_backtransform``. Returns ``None`` when the record cannot be used (missing
    estimate, non-positive SE, out-of-range proportion/correlation).
    """
    if e.estimate is None:
        return None
    est, se = float(e.estimate), e.se
    scale = _analysis_scale(e.measure)

    if scale == "log":
        if se is None and e.ci_lower is not None and e.ci_upper is not None:
            if e.ci_lower <= 0 or e.ci_upper <= 0 or est <= 0:
                return None
            return math.log(est), _se_from_ci(math.log(e.ci_lower), math.log(e.ci_upper))
        if se is None or se <= 0:
            return None
        return (math.log(est), se) if est > 0 else None

    if scale == "logit":
        if not (0.0 < est < 1.0):                       # a proportion must be in (0,1)
            return None
        if se is None and e.ci_lower is not None and e.ci_upper is not None:
            if not (0.0 < e.ci_lower < 1.0 and 0.0 < e.ci_upper < 1.0):
                return None
            return _logit(est), _se_from_ci(_logit(e.ci_lower), _logit(e.ci_upper))
        if se is None or se <= 0:
            return None
        return _logit(est), se / (est * (1.0 - est))    # delta-method SE on logit

    if scale == "ztrans":
        if not (-1.0 < est < 1.0):
            return None
        z = math.atanh(est)
        if se is None and e.ci_lower is not None and e.ci_upper is not None:
            if not (-1.0 < e.ci_lower < 1.0 and -1.0 < e.ci_upper < 1.0):
                return None
            return z, _se_from_ci(math.atanh(e.ci_lower), math.atanh(e.ci_upper))
        if se is None or se <= 0:
            return None
        return z, se / (1.0 - est ** 2)                 # delta-method SE on Fisher-z

    # identity scale (MD, SMD, RD, …)
    if se is None and e.ci_lower is not None and e.ci_upper is not None:
        se = _se_from_ci(e.ci_lower, e.ci_upper)
    if se is None or se <= 0:
        return None
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


def tau2_qprofile_ci(ys, vs, level=0.95):
    """95% CI for τ² by the Q-profile method (Viechtbauer 2007).

    Solves the generalized-Q estimating equation Q_gen(τ²) = χ²_{k-1; α} at the
    two tail quantiles. This is the interval ``metafor`` reports as the
    ``tau^2`` CI and is exact under the random-effects model, unlike Wald
    intervals which misbehave near the τ²=0 boundary.
    """
    ys, vs = np.asarray(ys, float), np.asarray(vs, float)
    k = len(ys)
    df = k - 1
    if df < 1:
        return None, None

    def q_gen(t2):
        w = 1.0 / (vs + t2)
        mu = np.sum(w * ys) / np.sum(w)
        return float(np.sum(w * (ys - mu) ** 2))

    alpha = 1.0 - level
    q_lo = float(scipy_stats.chi2.ppf(alpha / 2, df))       # for the upper τ² bound
    q_hi = float(scipy_stats.chi2.ppf(1 - alpha / 2, df))   # for the lower τ² bound

    def solve(target):
        # q_gen is strictly decreasing in τ²; bracket then bisect.
        if q_gen(0.0) <= target:
            return 0.0
        lo, hi = 0.0, max(1.0, np.max(vs))
        for _ in range(200):
            if q_gen(hi) <= target:
                break
            hi *= 2
            if hi > 1e12:
                return None
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if q_gen(mid) > target:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    lower = solve(q_hi) or 0.0
    upper = solve(q_lo)
    return lower, upper


def meta_regression(ys, vs, X, labels=None, tau2_method="REML", knha=True):
    """Mixed-effects meta-regression by weighted least squares (Knapp-Hartung).

    ``X`` is a list of moderator rows (an intercept column is prepended). τ² is
    estimated once from the null model (method-of-moments residual heterogeneity)
    and treated as known when fitting the coefficients — the standard
    two-step mixed-effects approach. With ``knha`` the coefficient tests use the
    Knapp-Hartung t-adjustment, which controls the type-I error far better than
    the normal approximation.
    """
    ys = np.asarray(ys, float)
    vs = np.asarray(vs, float)
    X = np.asarray(X, float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    n, p_cov = X.shape
    Xd = np.column_stack([np.ones(n), X])
    p = Xd.shape[1]
    if n <= p:
        return None
    # Residual-heterogeneity τ². REML via Fisher scoring on the weighted
    # residual-projection matrix P = W − WX(XᵀWX)⁻¹XᵀW (Viechtbauer 2005);
    # method-of-moments (DerSimonian-Kacker) otherwise.
    reml = tau2_method.upper() == "REML"
    tau2 = 0.0
    for _ in range(200):
        w = 1.0 / (vs + tau2)
        W = np.diag(w)
        XtWX = Xd.T @ W @ Xd
        XtWX_inv = np.linalg.pinv(XtWX)
        P = W - W @ Xd @ XtWX_inv @ Xd.T @ W
        if reml:
            Py = P @ ys
            num = float(Py @ Py) - float(np.trace(P))       # yᵀPPy − tr(P)
            den = float(np.sum(P * P))                        # tr(PP), P symmetric
            new = max(0.0, tau2 + num / den) if den > 1e-12 else tau2
        else:
            beta = XtWX_inv @ Xd.T @ W @ ys
            resid = ys - Xd @ beta
            rss = float(resid @ (w * resid))
            trP = float(np.trace(P @ np.diag(vs)))
            new = max(0.0, (rss - (n - p)) / max(trP, 1e-12))
        if abs(new - tau2) < 1e-9:
            tau2 = new
            break
        tau2 = new
    w = 1.0 / (vs + tau2)
    W = np.diag(w)
    XtWX_inv = np.linalg.pinv(Xd.T @ W @ Xd)
    beta = XtWX_inv @ Xd.T @ W @ ys
    resid = ys - Xd @ beta
    dfr = n - p
    if knha:
        s2 = float(resid @ (w * resid)) / dfr
        cov = s2 * XtWX_inv
        crit_dist, crit_df = "t", dfr
    else:
        cov = XtWX_inv
        crit_dist, crit_df = "z", None
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    names = ["intercept"] + [f"beta{i+1}" for i in range(p_cov)]
    coeffs = []
    for name, b, s in zip(names, beta, se):
        stat = b / s if s else 0.0
        pval = float(2 * scipy_stats.t.sf(abs(stat), dfr)) if knha \
            else float(2 * scipy_stats.norm.sf(abs(stat)))
        coeffs.append({"term": name, "estimate": round(float(b), 4),
                       "se": round(float(s), 4), "stat": round(float(stat), 4),
                       "p": round(pval, 4)})
    # Omnibus test of the moderators (all slopes = 0).
    QM = QM_p = None
    if p_cov >= 1:
        Bs = beta[1:]
        Cov_s = cov[1:, 1:]
        try:
            QM = float(Bs @ np.linalg.solve(Cov_s, Bs))
            if knha:
                QM /= p_cov
                QM_p = float(scipy_stats.f.sf(QM, p_cov, dfr))
            else:
                QM_p = float(scipy_stats.chi2.sf(QM, p_cov))
        except np.linalg.LinAlgError:
            pass
    return {"coefficients": coeffs, "tau2": round(tau2, 4), "test_dist": crit_dist,
            "df": crit_df, "QM": (round(QM, 3) if QM is not None else None),
            "QM_p": (round(QM_p, 5) if QM_p is not None else None), "k": n}


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
                 moderator=False, outcome="") -> Optional[MetaAnalysisResult]:
    labels = labels or [f"study {i+1}" for i in range(len(effects))]
    rows, used, groups, mods = [], [], [], []
    for lab, e in zip(labels, effects):
        u = _usable(e)
        if u is not None:
            rows.append(u)
            used.append(lab)
            groups.append(getattr(e, "subgroup", None))
            mods.append(getattr(e, "moderator", None))
    k = len(rows)
    if k == 0:
        return None
    ys = [r[0] for r in rows]
    vs = [r[1] ** 2 for r in rows]
    bt = _backtransform(measure)   # inverse of the analysis-scale transform

    res = _pool(ys, vs, model=model, tau2_method=tau2_method, knha=knha)
    het = _heterogeneity(res["Q"], res["Q_df"], k)
    se_re = float(math.sqrt(1.0 / np.sum(1.0 / (np.asarray(vs) + res["tau2"]))))

    forest = []
    wsum = sum(1.0 / s for s in vs)
    for lab, (y, se) in zip(used, rows):
        lo, hi = y - 1.96 * se, y + 1.96 * se
        # Display each study on its natural scale by back-transforming the
        # analysis-scale (log / logit / Fisher-z) estimate and CI.
        forest.append({"study": lab,
                       "estimate": round(bt(y), 4),
                       "ci_lower": round(bt(lo), 4),
                       "ci_upper": round(bt(hi), 4),
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

    if model == "random" and k >= 2:
        t2_lo, t2_hi = tau2_qprofile_ci(ys, vs)
        if t2_lo is not None:
            out.tau_squared_ci_lower = round(t2_lo, 4)
        if t2_hi is not None:
            out.tau_squared_ci_upper = round(t2_hi, 4)

    if prediction_interval_ and model == "random":
        pl, pu = prediction_interval(res["estimate"], se_re, res["tau2"], k)
        if pl is not None:
            out.pi_lower = round(bt(pl), 4)
            out.pi_upper = round(bt(pu), 4)
    if subgroup and any(g is not None for g in groups):
        sg = subgroup_analysis(ys, vs, groups, model=model, tau2_method=tau2_method, knha=knha, bt=bt)
        out.subgroups, out.q_between = sg["subgroups"], sg["q_between"]
        out.q_between_df, out.q_between_p = sg["q_between_df"], sg["q_between_p"]
    if moderator and sum(m is not None for m in mods) >= k and k >= 4:
        idx = [i for i, m in enumerate(mods) if m is not None]
        mr = meta_regression([ys[i] for i in idx], [vs[i] for i in idx],
                             [[mods[i]] for i in idx], tau2_method=tau2_method, knha=knha)
        if mr is not None:
            out.metareg = mr
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
    bt = _backtransform(measure)
    for e in effects:
        u = _usable(e)
        if u is not None:
            y, se = u
            # se stays on the analysis scale (funnel y-axis); estimate is shown
            # on the natural scale.
            out.append({"estimate": round(bt(y), 4), "se": round(se, 4)})
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
