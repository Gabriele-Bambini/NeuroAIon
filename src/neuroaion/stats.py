"""Quantitative synthesis primitives (PRISMA item 13).

A small, dependency-light implementation of inverse-variance meta-analysis with
the DerSimonian–Laird random-effects estimator, plus Cohen's kappa for
inter-rater agreement. These are computed deterministically in Python — the
language model is never asked to produce a pooled estimate or a heterogeneity
statistic.
"""
from __future__ import annotations

import math
from typing import Optional

from scipy import stats as scipy_stats

from .models import EffectEstimate, MetaAnalysisResult


def _se_from_ci(lo: float, hi: float) -> float:
    # 95% CI → SE assuming normal approximation.
    return (hi - lo) / (2 * 1.959963985)


def _usable(e: EffectEstimate) -> Optional[tuple[float, float]]:
    """Return (effect, se) if the estimate carries enough information, else None.

    For ratio measures (OR/RR/HR) the analysis is performed on the log scale.
    """
    if e.estimate is None:
        return None
    est = float(e.estimate)
    se = e.se
    if se is None and e.ci_lower is not None and e.ci_upper is not None:
        if e.measure.upper() in {"OR", "RR", "HR"}:
            if e.ci_lower <= 0 or e.ci_upper <= 0 or est <= 0:
                return None
            return math.log(est), _se_from_ci(math.log(e.ci_lower), math.log(e.ci_upper))
        se = _se_from_ci(e.ci_lower, e.ci_upper)
    if se is None or se <= 0:
        return None
    if e.measure.upper() in {"OR", "RR", "HR"}:
        if est <= 0:
            return None
        return math.log(est), se
    return est, se


def meta_analyze(effects: list[EffectEstimate], *, measure: str = "SMD",
                 model: str = "random",
                 labels: Optional[list[str]] = None) -> Optional[MetaAnalysisResult]:
    """Inverse-variance pooling. Random effects uses DerSimonian–Laird tau²."""
    rows: list[tuple[str, float, float]] = []
    labels = labels or [f"study {i+1}" for i in range(len(effects))]
    for lab, e in zip(labels, effects):
        u = _usable(e)
        if u is not None:
            rows.append((lab, u[0], u[1]))
    k = len(rows)
    if k == 0:
        return None

    log_scale = measure.upper() in {"OR", "RR", "HR"}
    ys = [r[1] for r in rows]
    ses = [r[2] for r in rows]
    ws = [1.0 / (s * s) for s in ses]

    # Fixed-effect pooled estimate.
    fe = sum(w * y for w, y in zip(ws, ys)) / sum(ws)

    # Heterogeneity (Cochran's Q, I², DerSimonian–Laird tau²).
    q = sum(w * (y - fe) ** 2 for w, y in zip(ws, ys))
    df = k - 1
    c = sum(ws) - (sum(w * w for w in ws) / sum(ws)) if sum(ws) else 0
    tau2 = max(0.0, (q - df) / c) if c > 0 else 0.0
    i2 = max(0.0, (q - df) / q) * 100 if q > 0 else 0.0

    if model == "random" and tau2 > 0:
        ws = [1.0 / (s * s + tau2) for s in ses]

    pooled = sum(w * y for w, y in zip(ws, ys)) / sum(ws)
    se_pooled = math.sqrt(1.0 / sum(ws))
    z = pooled / se_pooled if se_pooled else 0.0
    p = 2 * (1 - scipy_stats.norm.cdf(abs(z)))
    ci_lo = pooled - 1.959963985 * se_pooled
    ci_hi = pooled + 1.959963985 * se_pooled

    forest = []
    for lab, y, s in rows:
        lo, hi = y - 1.96 * s, y + 1.96 * s
        forest.append({
            "study": lab,
            "estimate": round(math.exp(y) if log_scale else y, 4),
            "ci_lower": round(math.exp(lo) if log_scale else lo, 4),
            "ci_upper": round(math.exp(hi) if log_scale else hi, 4),
            "weight_pct": round(100 * (1.0 / (s * s)) / sum(1.0 / (x[2] ** 2) for x in rows), 1),
        })

    return MetaAnalysisResult(
        measure=measure, model=model, k_studies=k,
        pooled_estimate=round(math.exp(pooled) if log_scale else pooled, 4),
        ci_lower=round(math.exp(ci_lo) if log_scale else ci_lo, 4),
        ci_upper=round(math.exp(ci_hi) if log_scale else ci_hi, 4),
        p_value=round(float(p), 5),
        i_squared=round(i2, 1),
        tau_squared=round(tau2, 4),
        q_statistic=round(q, 3),
        forest=forest,
    )


def cohen_kappa(a: list[str], b: list[str]) -> Optional[float]:
    """Cohen's kappa for two reviewers' categorical decisions over the same items."""
    if not a or len(a) != len(b):
        return None
    cats = sorted(set(a) | set(b))
    idx = {c: i for i, c in enumerate(cats)}
    n = len(a)
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    pa = [0.0] * len(cats)
    pb = [0.0] * len(cats)
    for x, y in zip(a, b):
        pa[idx[x]] += 1 / n
        pb[idx[y]] += 1 / n
    expected = sum(pa[i] * pb[i] for i in range(len(cats)))
    if expected >= 1.0:
        return 1.0
    return round((observed - expected) / (1 - expected), 3)


def funnel_points(effects: list[EffectEstimate],
                  measure: str = "SMD") -> list[dict]:
    """Per-study (effect, se) pairs for a funnel plot, on the analysis scale."""
    out = []
    log_scale = measure.upper() in {"OR", "RR", "HR"}
    for e in effects:
        u = _usable(e)
        if u is not None:
            y, se = u
            out.append({"estimate": round(math.exp(y) if log_scale else y, 4),
                        "se": round(se, 4)})
    return out


def eggers_test(effects: list[EffectEstimate]) -> Optional[dict]:
    """Egger's regression test for small-study effects / funnel asymmetry.

    Regresses the standard normal deviate (y_i / SE_i) on precision (1 / SE_i)
    via OLS; a non-zero intercept indicates asymmetry. Returns the intercept,
    its two-sided p-value, and k. Needs k >= 3 (and is under-powered below ~10).
    """
    import numpy as np

    pts = [u for u in (_usable(e) for e in effects) if u is not None]
    if len(pts) < 3:
        return None
    y = np.array([p[0] for p in pts], dtype=float)
    se = np.array([p[1] for p in pts], dtype=float)
    snd = y / se                 # standard normal deviate (response)
    precision = 1.0 / se         # predictor
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
    return {"intercept": round(float(beta[0]), 4), "p": round(p, 4), "k": n,
            "underpowered": n < 10}
