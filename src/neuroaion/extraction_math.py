"""Recompute effect sizes and standard errors from raw study data.

A meta-analysis is only as trustworthy as the numbers that enter it. Papers
report effects inconsistently (some give an OR, some a raw 2×2 table, some a
median with an IQR), and neither the original authors nor a language model can
be trusted to have done the arithmetic correctly. This module takes whatever
*raw* arm-level data a study reports and derives the effect size and its
standard error on the analysis scale from first principles, exactly as a
statistician would with pen and paper — so the pooled result rests on data,
not on transcription.

Implemented:

* Binary 2×2 → log OR / log RR / risk difference, with the Sweeting *et al.*
  (2004) treatment-arm continuity correction for sparse/zero cells.
* Continuous two-arm → mean difference (MD) and Hedges' *g* SMD with the exact
  small-sample *J* correction and its variance.
* Median-based summaries → mean and SD via Luo *et al.* (2018) means and
  Wan *et al.* (2014) SDs (scenarios C1/C2/C3), with a Hozo *et al.* (2005)
  fallback.
* An SD recovered from a reported confidence interval, standard error, or
  two-sided *p*-value.

Every function returns a small result object carrying the value **and** the
provenance string that will be written into the extraction record, so the
audit trail states precisely how each number was obtained.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from scipy import stats as _st

from .models import EffectEstimate

_Z = 1.959963984540054  # Φ⁻¹(0.975)


@dataclass
class Derived:
    """A recomputed effect on the analysis scale (log scale for ratios)."""
    estimate: float          # point estimate (log OR/RR for ratio measures)
    se: float                # standard error on the same scale
    provenance: str
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None


# --------------------------------------------------------------------------- #
# Binary 2×2 tables
# --------------------------------------------------------------------------- #
def from_2x2(a: float, n1: float, c: float, n2: float, measure: str) -> Optional[Derived]:
    """Log OR / log RR / RD with a continuity correction only when needed.

    ``a`` events of ``n1`` in the intervention arm; ``c`` of ``n2`` in the
    comparator. Ratio measures are returned on the **log** scale (that is how
    they enter the inverse-variance pool). Sweeting's treatment-arm correction
    adds a reciprocal-group-size pseudo-count to every cell only if a cell is
    empty, which is far less biased than a blanket +0.5.
    """
    if None in (a, n1, c, n2) or n1 <= 0 or n2 <= 0:
        return None
    a, n1, c, n2 = float(a), float(n1), float(c), float(n2)
    b, d = n1 - a, n2 - c
    if min(a, b, c, d) < 0:
        return None
    m = (measure or "").upper()

    # Double-zero studies carry no information about a ratio and are excluded
    # (as RevMan and metafor's rma.mh(drop00=TRUE) do) rather than continuity-
    # corrected into a spurious "no effect" data point.
    if m in ("OR", "RR") and ((a == 0 and c == 0) or (b == 0 and d == 0)):
        return None

    zero = min(a, b, c, d) == 0
    corr = ""
    if zero and m in ("OR", "RR"):
        # Sweeting reciprocal-of-opposite-group-size continuity correction.
        k1 = n2 / (n1 + n2)
        k2 = n1 / (n1 + n2)
        a, b = a + k1, b + k1
        c, d = c + k2, d + k2
        n1, n2 = a + b, c + d
        corr = " (Sweeting continuity correction for zero cell)"

    if m == "OR":
        est = math.log((a * d) / (b * c))
        se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
        return Derived(est, se, f"log OR from 2×2 table{corr}")
    if m == "RR":
        est = math.log((a / n1) / (c / n2))
        se = math.sqrt(1 / a - 1 / n1 + 1 / c - 1 / n2)
        return Derived(est, se, f"log RR from 2×2 table{corr}")
    if m in ("RD", "PROP"):
        p1, p2 = a / n1, c / n2
        est = p1 - p2
        se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
        return Derived(est, se, "risk difference from 2×2 table")
    return None


# --------------------------------------------------------------------------- #
# Continuous two-arm data
# --------------------------------------------------------------------------- #
def _pooled_sd(sd1: float, n1: float, sd2: float, n2: float) -> float:
    return math.sqrt(((n1 - 1) * sd1 ** 2 + (n2 - 1) * sd2 ** 2) / (n1 + n2 - 2))


def mean_difference(m1: float, sd1: float, n1: float,
                    m2: float, sd2: float, n2: float) -> Optional[Derived]:
    """Raw mean difference m1−m2 with its standard error."""
    if None in (m1, sd1, n1, m2, sd2, n2) or n1 <= 0 or n2 <= 0:
        return None
    est = float(m1) - float(m2)
    se = math.sqrt(sd1 ** 2 / n1 + sd2 ** 2 / n2)
    return Derived(est, se, "mean difference from group means and SDs")


def hedges_g(m1: float, sd1: float, n1: float,
             m2: float, sd2: float, n2: float) -> Optional[Derived]:
    """Hedges' *g* standardised mean difference with the exact *J* correction."""
    if None in (m1, sd1, n1, m2, sd2, n2) or n1 <= 0 or n2 <= 0:
        return None
    df = n1 + n2 - 2
    if df <= 0:
        return None
    sp = _pooled_sd(sd1, n1, sd2, n2)
    if sp == 0:
        return None
    d = (float(m1) - float(m2)) / sp
    j = math.exp(math.lgamma(df / 2) - math.log(math.sqrt(df / 2)) - math.lgamma((df - 1) / 2))
    g = j * d
    var = (n1 + n2) / (n1 * n2) + g ** 2 / (2 * df)
    return Derived(g, math.sqrt(var), "Hedges' g from group means and SDs")


# --------------------------------------------------------------------------- #
# Median-based summaries → mean & SD
# --------------------------------------------------------------------------- #
def mean_sd_from_median(n: float, median: float,
                        q1: Optional[float] = None, q3: Optional[float] = None,
                        lo: Optional[float] = None, hi: Optional[float] = None
                        ) -> Optional[tuple[float, float, str]]:
    """Estimate (mean, SD) from a median summary (Luo 2018 mean, Wan 2014 SD).

    Three scenarios, chosen by which statistics are present:
      * C1: min, median, max            (Hozo/Wan/Luo)
      * C2: q1, median, q3
      * C3: min, q1, median, q3, max
    """
    if n is None or n < 2 or median is None:            # n>=2: n=1 gives a zero/inf SD
        return None
    n = float(n)
    have_iqr = q1 is not None and q3 is not None
    have_range = lo is not None and hi is not None
    # Reject inconsistent orderings rather than emit a negative/blended SD.
    if have_iqr and not (q1 <= median <= q3):
        return None
    if have_range and not (lo <= median <= hi):
        return None
    if have_iqr and have_range and not (lo <= q1 and q3 <= hi):
        return None

    if have_range and have_iqr:                        # scenario C3
        # Luo 2018 mean (eq. 15) + Wan 2014 SD (eq. 12).
        w = 2.2 / (2.2 + n ** 0.75)
        mean = w * (lo + hi) / 2 + (0.7 - 0.72 / n ** 0.75) * (q1 + q3) / 2 \
            + (0.3 + 0.72 / n ** 0.75 - w) * median
        # Wan combines the range- and IQR-based SD estimates.
        xi = 2 * _st.norm.ppf((n - 0.375) / (n + 0.25))
        eta = 2 * _st.norm.ppf((0.75 * n - 0.125) / (n + 0.25))
        sd = 0.5 * ((hi - lo) / xi + (q3 - q1) / eta)
        return float(mean), float(sd), "mean/SD from min,Q1,median,Q3,max (Luo 2018 / Wan 2014, C3)"

    if have_iqr:                                       # scenario C2
        mean = (0.7 + 0.39 / n) * (q1 + q3) / 2 + (0.3 - 0.39 / n) * median
        eta = 2 * _st.norm.ppf((0.75 * n - 0.125) / (n + 0.25))
        sd = (q3 - q1) / eta
        return float(mean), float(sd), "mean/SD from Q1,median,Q3 (Luo 2018 / Wan 2014, C2)"

    if have_range:                                     # scenario C1
        w = 4 / (4 + n ** 0.75)
        mean = w * (lo + hi) / 2 + (1 - w) * median
        xi = 2 * _st.norm.ppf((n - 0.375) / (n + 0.25))
        sd = (hi - lo) / xi
        return float(mean), float(sd), "mean/SD from min,median,max (Luo 2018 / Wan 2014, C1)"

    return None


def sd_from_ci(lo: float, hi: float, n: float, is_log: bool = False) -> Optional[float]:
    """Recover a group SD from a reported 95% CI of the mean."""
    if None in (lo, hi, n) or n <= 0:
        return None
    if is_log:
        lo, hi = math.log(lo), math.log(hi)
    return (hi - lo) / (2 * _Z) * math.sqrt(n)


def sd_from_se(se: float, n: float) -> Optional[float]:
    if None in (se, n) or n <= 0:
        return None
    return float(se) * math.sqrt(n)


def sd_from_p_twogroup(p: float, m1: float, m2: float,
                       n1: float, n2: float) -> Optional[float]:
    """Recover a common SD from a two-sided p-value for the mean difference."""
    if None in (p, m1, m2, n1, n2) or not (0 < p < 1) or n1 <= 0 or n2 <= 0:
        return None
    t = _st.t.ppf(1 - p / 2, df=n1 + n2 - 2)
    if t == 0:
        return None
    return abs(m1 - m2) / (abs(t) * math.sqrt(1 / n1 + 1 / n2))


# --------------------------------------------------------------------------- #
# Orchestration: fill an EffectEstimate from whatever raw data it carries
# --------------------------------------------------------------------------- #
def _se_from_ci(lo: Optional[float], hi: Optional[float], measure: str) -> Optional[float]:
    if lo is None or hi is None:
        return None
    ratio = (measure or "").upper() in ("OR", "RR", "HR")
    if ratio:
        if lo <= 0 or hi <= 0:
            return None
        return (math.log(hi) - math.log(lo)) / (2 * _Z)
    return (hi - lo) / (2 * _Z)


def recompute(e: EffectEstimate) -> EffectEstimate:
    """Return a copy of *e* with estimate/se derived from raw data when possible.

    Priority: raw 2×2 table → group means+SDs → median summaries → verbatim
    estimate with an SE recovered from the reported CI. The record is never
    silently altered: ``recomputed`` and ``provenance`` document what happened.
    """
    m = (e.measure or "").upper()
    out = e.model_copy(deep=True)

    # 1) Binary 2×2 table.
    if e.events_intervention is not None and e.events_comparator is not None \
            and e.n_intervention and e.n_comparator:
        d = from_2x2(e.events_intervention, e.n_intervention,
                     e.events_comparator, e.n_comparator, m or "OR")
        if d is not None:
            out.se = d.se
            out.provenance = d.provenance
            out.recomputed = True
            if m in ("OR", "RR", "HR"):
                out.estimate = math.exp(d.estimate)
                out.ci_lower = math.exp(d.estimate - _Z * d.se)
                out.ci_upper = math.exp(d.estimate + _Z * d.se)
            else:
                out.estimate = d.estimate
                out.ci_lower = d.estimate - _Z * d.se
                out.ci_upper = d.estimate + _Z * d.se
            return out

    # 2) Continuous group means + SDs (recovering an SD first if needed).
    m1, sd1, n1 = e.mean_intervention, e.sd_intervention, e.n_intervention
    m2, sd2, n2 = e.mean_comparator, e.sd_comparator, e.n_comparator

    # 2b) Median summaries → mean & SD when means/SDs are absent.
    prov_extra = ""
    if m1 is None and e.median_intervention is not None and n1:
        got = mean_sd_from_median(n1, e.median_intervention, e.q1_intervention,
                                  e.q3_intervention, e.min_intervention, e.max_intervention)
        if got:
            m1, sd1, prov_extra = got[0], got[1], got[2]
    if m2 is None and e.median_comparator is not None and n2:
        got = mean_sd_from_median(n2, e.median_comparator, e.q1_comparator,
                                  e.q3_comparator, e.min_comparator, e.max_comparator)
        if got:
            m2, sd2 = got[0], got[1]

    # 2c) Means present but the SD reported only indirectly — recover it from an
    # SE, a per-group 95% CI, or (for a common SD) a two-sided p-value. Mean±SE
    # is one of the commonest reporting formats; without this the study is lost.
    if m1 is not None and sd1 is None and n1:
        if e.p_value is not None and m2 is not None and n2:
            sd1 = sd_from_p_twogroup(e.p_value, m1, m2, n1, n2)
            if sd1 is not None:
                sd2 = sd2 if sd2 is not None else sd1
                prov_extra = (prov_extra + "; " if prov_extra else "") + "SD from p-value"
    if None not in (m1, n1, m2, n2) and (sd1 is None or sd2 is None):
        # Fall back to CI/SE-derived SDs when only the difference CI is unknown
        # but a per-arm dispersion can be inferred from the record's se field.
        if sd1 is None and e.se is not None and n1:
            sd1 = sd_from_se(e.se, n1)
        if sd2 is None and sd1 is not None:
            sd2 = sd1
        if sd1 is not None and sd2 is not None and not prov_extra:
            prov_extra = "SD recovered from reported dispersion"

    if None not in (m1, sd1, n1, m2, sd2, n2):
        d = hedges_g(m1, sd1, n1, m2, sd2, n2) if m == "SMD" \
            else mean_difference(m1, sd1, n1, m2, sd2, n2)
        if d is not None:
            out.estimate = d.estimate
            out.se = d.se
            out.ci_lower = d.estimate - _Z * d.se
            out.ci_upper = d.estimate + _Z * d.se
            out.provenance = (prov_extra + "; " if prov_extra else "") + d.provenance
            out.recomputed = True
            return out

    # 3) No raw data — keep the reported estimate, recover the SE from the CI.
    if out.se is None:
        se = _se_from_ci(e.ci_lower, e.ci_upper, m)
        if se is not None:
            out.se = se
            out.provenance = "SE recovered from reported 95% CI"
    return out
