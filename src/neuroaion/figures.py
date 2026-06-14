"""Publication-quality figures (matplotlib backend) — forest, funnel, PRISMA flow.

Vector output (PDF) for the LaTeX paper and PNG for HTML/ReportLab. Reads the
existing ``MetaAnalysisResult`` / ``PrismaFlow`` models, tolerating optional
fields (prediction interval, subgroups, register/other-methods counts) via
``getattr`` so it works whether or not the model has been extended.

Geometry follows Cochrane / RevMan and the official PRISMA 2020 templates:
forest — square AREA ∝ weight, log axis for ratio measures, summary diamond,
95% prediction-interval bar, heterogeneity footer; funnel — inverted-SE axis,
contour-enhanced significance shading, pseudo-95% CI, Egger line.

Optional dependency: ``pip install neuroaion[figures]`` (matplotlib).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from .models import MetaAnalysisResult, PrismaFlow

RATIO = {"OR", "RR", "HR", "IRR", "ROM", "RATE RATIO"}

# Restrained journal palette.
C_SQ, C_DIA, C_PI = "#2b3a67", "#11151c", "#5a6b9a"
C_NULL, C_AXIS, C_POINT = "#9aa0a6", "#1a1a1a", "#2b6cb0"
C_FUNNEL = ["#ffffff", "#e9edf2", "#cfd8e3", "#aeb9cc"]   # p>.10, .05–.10, .01–.05, <.01
ROB_FILL = {"low": "#2e7d32", "some concerns": "#f9a825", "high": "#c62828"}


def _ratio(measure: str) -> bool:
    return (measure or "").strip().upper() in RATIO


# ── Forest ───────────────────────────────────────────────────────────────────
def build_forest_figure(meta: MetaAnalysisResult, *, treatment: str = "",
                        control: str = ""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon

    rows = list(meta.forest or [])
    if not rows:
        raise ValueError("no forest rows")
    ratio = _ratio(meta.measure)
    null = 1.0 if ratio else 0.0

    def T(v):                       # to plotting scale (log for ratio measures)
        return math.log10(v) if ratio else v

    vals = []
    for r in rows:
        vals += [r["ci_lower"], r["ci_upper"], r["estimate"]]
    for v in (meta.ci_lower, meta.ci_upper, meta.pooled_estimate):
        if v is not None:
            vals.append(v)
    vals.append(null)
    vals = [v for v in vals if v is not None and (not ratio or v > 0)]
    tvals = [T(v) for v in vals]
    lo, hi = min(tvals), max(tvals)
    if hi <= lo:
        hi = lo + 1.0
    pad = (hi - lo) * 0.12
    lo, hi = lo - pad, hi + pad

    # Layout: single axes in [0,1]×rows; effect mapped to band [PX0,PX1].
    PX0, PX1 = 0.40, 0.74
    LBL_X, EFF_X, WT_X = 0.005, 0.875, 0.995

    def X(v):
        return PX0 + (T(v) - lo) / (hi - lo) * (PX1 - PX0)

    # Prediction interval row?
    pi = _prediction_interval(meta, ratio)
    n_rows = len(rows)
    n_slots = n_rows + 2 + (1 if pi else 0)      # studies + spacer + overall (+ PI)
    fig_h = max(2.6, 0.36 * n_slots + 1.2)
    fig, ax = plt.subplots(figsize=(7.6, fig_h), dpi=150)
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.5, n_slots + 0.5)
    ax.axis("off")

    top = n_slots
    # null reference line
    ax.plot([X(null), X(null)], [0.2, top - 0.2], color=C_NULL, lw=0.9, ls="--", zorder=1)

    # square areas ∝ weight
    wmax = max((r.get("weight_pct", 0) or 0) for r in rows) or 1.0

    def fs(w):     # marker size in points^2, area ∝ weight
        return 28 + 300 * (w / wmax)

    # header
    ax.text(LBL_X, top + 0.15, "Study", fontsize=8, fontweight="bold", va="bottom")
    ax.text(EFF_X, top + 0.15, f"{meta.measure} [95% CI]", fontsize=8,
            fontweight="bold", va="bottom", ha="right")
    ax.text(WT_X, top + 0.15, "Weight", fontsize=8, fontweight="bold",
            va="bottom", ha="right")

    y = top - 1
    for r in rows:
        x1, x2, xe = X(r["ci_lower"]), X(r["ci_upper"]), X(r["estimate"])
        x1c, x2c = max(x1, PX0 - 0.005), min(x2, PX1 + 0.005)
        ax.plot([x1c, x2c], [y, y], color=C_AXIS, lw=1.0, zorder=3)
        # arrowheads for clipped CIs
        if x1 < PX0 - 0.005:
            ax.annotate("", xy=(PX0 - 0.02, y), xytext=(PX0 + 0.0, y),
                        arrowprops=dict(arrowstyle="-|>", color=C_AXIS, lw=1.0))
        if x2 > PX1 + 0.005:
            ax.annotate("", xy=(PX1 + 0.02, y), xytext=(PX1, y),
                        arrowprops=dict(arrowstyle="-|>", color=C_AXIS, lw=1.0))
        ax.scatter([xe], [y], s=fs(r.get("weight_pct", 0) or 0), marker="s",
                   color=C_SQ, zorder=4, edgecolors="none")
        ax.text(LBL_X, y, str(r.get("study", ""))[:34], fontsize=7.4, va="center")
        ax.text(EFF_X, y, f"{r['estimate']:.2f} [{r['ci_lower']:.2f}, {r['ci_upper']:.2f}]",
                fontsize=7.4, va="center", ha="right")
        ax.text(WT_X, y, f"{(r.get('weight_pct',0) or 0):.1f}%", fontsize=7.4,
                va="center", ha="right")
        y -= 1

    y -= 1   # spacer → overall row at y
    pe, pl, pu = meta.pooled_estimate, meta.ci_lower, meta.ci_upper
    dia = Polygon([(X(pl), y), (X(pe), y + 0.34), (X(pu), y), (X(pe), y - 0.34)],
                  closed=True, facecolor=C_DIA, edgecolor="none", zorder=5)
    ax.add_patch(dia)
    ax.text(LBL_X, y, f"Overall ({meta.model}-effects)", fontsize=7.6,
            fontweight="bold", va="center")
    ax.text(EFF_X, y, f"{pe:.2f} [{pl:.2f}, {pu:.2f}]", fontsize=7.6,
            fontweight="bold", va="center", ha="right")
    ax.text(WT_X, y, "100.0%", fontsize=7.6, fontweight="bold", va="center", ha="right")

    if pi:
        ypi = y - 1
        ax.plot([X(pi[0]), X(pi[1])], [ypi, ypi], color=C_PI, lw=1.6, zorder=4)
        for b in pi:
            ax.plot([X(b), X(b)], [ypi - 0.12, ypi + 0.12], color=C_PI, lw=1.6, zorder=4)
        ax.text(LBL_X, ypi, "95% prediction interval", fontsize=7.2, va="center",
                style="italic", color=C_PI)
        ax.text(EFF_X, ypi, f"[{pi[0]:.2f}, {pi[1]:.2f}]", fontsize=7.2,
                va="center", ha="right", color=C_PI)

    # axis line + ticks
    ax.plot([PX0, PX1], [0.0, 0.0], color=C_AXIS, lw=0.9)
    ticks = _nice_ticks(lo, hi, ratio)
    for tv in ticks:
        xt = PX0 + (tv - lo) / (hi - lo) * (PX1 - PX0)
        ax.plot([xt, xt], [-0.02, 0.0], color=C_AXIS, lw=0.8)
        lab = f"{10**tv:g}" if ratio else f"{tv:g}"
        ax.text(xt, -0.14, lab, fontsize=6.6, ha="center", va="top")
    # favours labels
    lft = f"Favours {treatment}" if treatment else ("Favours lower" if ratio else "Favours control")
    rgt = f"Favours {control}" if control else ("Favours higher" if ratio else "Favours intervention")
    ax.text((PX0 + X(null)) / 2, -0.42, lft, fontsize=6.4, ha="center", va="top")
    ax.text((X(null) + PX1) / 2, -0.42, rgt, fontsize=6.4, ha="center", va="top")

    # heterogeneity footer
    ax.text(LBL_X, -0.95, _het_line(meta), fontsize=6.8, va="top")
    oe = _overall_effect_line(meta)
    if oe:
        ax.text(LBL_X, -1.25, oe, fontsize=6.8, va="top")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.97, bottom=0.04)
    return fig


# ── Funnel ───────────────────────────────────────────────────────────────────
def build_funnel_figure(meta: MetaAnalysisResult):
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    if not meta.funnel or meta.pooled_estimate is None:
        raise ValueError("no funnel data")
    ratio = _ratio(meta.measure)

    def T(v):
        return math.log(v) if ratio else v

    pts = [(T(p["estimate"]), float(p["se"])) for p in meta.funnel
           if p.get("se") and (not ratio or p["estimate"] > 0)]
    if not pts:
        raise ValueError("no usable funnel points")
    est = np.array([e for e, _ in pts])
    se = np.array([s for _, s in pts])
    pooled, null = T(meta.pooled_estimate), 0.0 if ratio else 0.0
    se_max = float(se.max()) * 1.12 or 1.0

    fig, ax = plt.subplots(figsize=(5.6, 5.0), dpi=150)
    yy = np.linspace(0, se_max, 120)
    span = max(abs(est - null).max(), 1.96 * se_max) * 1.3
    # contour significance bands about the null
    ax.fill_betweenx(yy, null - 2.576 * yy, null - span, color=C_FUNNEL[3], zorder=0)
    ax.fill_betweenx(yy, null + 2.576 * yy, null + span, color=C_FUNNEL[3], zorder=0)
    ax.fill_betweenx(yy, null - 2.576 * yy, null - 1.96 * yy, color=C_FUNNEL[2], zorder=0)
    ax.fill_betweenx(yy, null + 1.96 * yy, null + 2.576 * yy, color=C_FUNNEL[2], zorder=0)
    ax.fill_betweenx(yy, null - 1.96 * yy, null - 1.645 * yy, color=C_FUNNEL[1], zorder=0)
    ax.fill_betweenx(yy, null + 1.645 * yy, null + 1.96 * yy, color=C_FUNNEL[1], zorder=0)
    ax.fill_betweenx(yy, null - 1.645 * yy, null + 1.645 * yy, color=C_FUNNEL[0], zorder=0)
    # pseudo-95% CI about pooled + reference lines
    ax.plot(pooled - 1.96 * yy, yy, color="#444", lw=0.9, ls="--", zorder=2)
    ax.plot(pooled + 1.96 * yy, yy, color="#444", lw=0.9, ls="--", zorder=2)
    ax.axvline(pooled, color="#444", lw=1.0, zorder=2)
    ax.axvline(null, color=C_NULL, lw=0.8, ls=":", zorder=2)
    ax.scatter(est, se, s=26, color=C_POINT, edgecolors="white", lw=0.4, zorder=4)
    # Egger weighted-regression line
    eg = _egger_line(est, se)
    if eg is not None:
        a, b = eg
        ax.plot(a + b * yy, yy, color="#b03030", lw=1.2, zorder=3)
        if meta.eggers_p is not None:
            ax.text(0.03, 0.05, f"Egger P = {meta.eggers_p:.3f}",
                    transform=ax.transAxes, fontsize=7.5, color="#b03030")

    ax.set_xlim(null - span, null + span)
    ax.set_ylim(se_max, 0)
    if ratio:
        ax.set_xticklabels([f"{math.exp(t):.2g}" for t in ax.get_xticks()])
    ax.set_xlabel(f"Effect size ({meta.measure})", fontsize=8.5)
    ax.set_ylabel("Standard error", fontsize=8.5)
    ax.tick_params(labelsize=7.5)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.legend(handles=[Patch(facecolor=C_FUNNEL[0], ec="#ccc", label="p > 0.10"),
                       Patch(facecolor=C_FUNNEL[1], ec="#ccc", label="0.05–0.10"),
                       Patch(facecolor=C_FUNNEL[2], ec="#ccc", label="0.01–0.05"),
                       Patch(facecolor=C_FUNNEL[3], ec="#ccc", label="< 0.01")],
              fontsize=6.5, loc="upper right", frameon=False, handlelength=1.1,
              title="2-sided p", title_fontsize=6.5)
    fig.tight_layout()
    return fig


# ── PRISMA 2020 flow ─────────────────────────────────────────────────────────
def build_prisma_figure(flow: PrismaFlow):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

    def n(v):
        return f"{int(v):,}"

    db = getattr(flow, "records_from_databases", 0) or (
        sum(flow.records_identified.values()) or flow.records_total)
    reg = getattr(flow, "records_from_registers", 0) or 0
    auto = getattr(flow, "auto_excluded", 0)
    other_rm = getattr(flow, "removed_other_reasons", 0)
    excl = list(flow.reports_excluded.items())

    fig, ax = plt.subplots(figsize=(8.6, 10.2), dpi=150)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    BOX_EC, ARROW, TXT, BAND = "#2f3a4a", "#2f3a4a", "#15202b", "#dbe5f1"

    def band(y0, y1, label):
        ax.add_patch(Rectangle((6, y0), 94, y1 - y0, facecolor=BAND, alpha=0.30,
                               edgecolor="none", zorder=0))
        ax.add_patch(Rectangle((1.5, y0), 4, y1 - y0, facecolor=BAND, edgecolor="none",
                               zorder=0))
        ax.text(3.5, (y0 + y1) / 2, label, rotation=90, ha="center", va="center",
                fontsize=10, fontweight="bold", color="#33425a")

    def box(cx, cy, w, h, lines, fc="#ffffff", fontsize=8, weight="normal"):
        ax.add_patch(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h,
                     boxstyle="round,pad=0,rounding_size=1.4", linewidth=0.9,
                     edgecolor=BOX_EC, facecolor=fc, zorder=2))
        ax.text(cx - w / 2 + 1.5, cy, "\n".join(lines), ha="left", va="center",
                fontsize=fontsize, color=TXT, weight=weight, zorder=3, linespacing=1.3)
        return (cx, cy, w, h)

    def varrow(a, b):
        ax.add_patch(FancyArrowPatch((a[0], a[1] - a[3] / 2), (b[0], b[1] + b[3] / 2),
                     arrowstyle="-|>", mutation_scale=11, lw=0.9, color=ARROW, zorder=1))

    def harrow(a, b):
        ax.add_patch(FancyArrowPatch((a[0] + a[2] / 2, a[1]), (b[0] - b[2] / 2, b[1]),
                     arrowstyle="-|>", mutation_scale=11, lw=0.9, color=ARROW, zorder=1))

    band(74, 99, "Identification")
    band(20, 74, "Screening")
    band(3, 20, "Included")
    LX, SX, BW, SBW = 30, 73, 34, 34

    d1 = box(LX, 90, BW, 10, ["Records identified from:",
             f"   Databases (n = {n(db)})", f"   Registers (n = {n(reg)})"], fontsize=8.2)
    d2 = box(SX, 90, SBW, 10, ["Records removed before screening:",
             f"   Duplicates removed (n = {n(flow.duplicates_removed)})",
             f"   Automation-excluded (n = {n(auto)})",
             f"   Other reasons (n = {n(other_rm)})"], fontsize=7.2)
    d3 = box(LX, 66, BW, 6, [f"Records screened (n = {n(flow.records_screened)})"])
    d4 = box(SX, 66, SBW, 6, [f"Records excluded (n = {n(flow.records_excluded_screening)})"],
             fontsize=7.6)
    d5 = box(LX, 53, BW, 6, [f"Reports sought for retrieval (n = {n(flow.reports_sought)})"])
    d6 = box(SX, 53, SBW, 6, [f"Reports not retrieved (n = {n(flow.reports_not_retrieved)})"],
             fontsize=7.6)
    d7 = box(LX, 40, BW, 6, [f"Reports assessed for eligibility (n = {n(flow.reports_assessed)})"])
    excl_lines = ["Reports excluded:"] + [f"   {k} (n = {v})" for k, v in excl[:6]] or \
                 ["Reports excluded: none"]
    d8 = box(SX, 38, SBW, max(7, 2 + 1.4 * len(excl[:6])), excl_lines, fontsize=7.0)
    i1 = box((LX + LX) / 2, 11, BW + 8, 8,
             [f"Studies included in review (n = {n(flow.studies_included)})",
              f"Reports of included studies (n = {n(getattr(flow,'reports_of_included',flow.studies_included))})"],
             fc="#eef3f9", weight="bold", fontsize=8.2)

    varrow(d1, d3); varrow(d3, d5); varrow(d5, d7); varrow(d7, i1)
    harrow(d1, d2); harrow(d3, d4); harrow(d5, d6); harrow(d7, d8)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    return fig


# ── helpers ──────────────────────────────────────────────────────────────────
def _nice_ticks(lo, hi, ratio):
    if ratio:
        nice = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50]
        return [math.log10(t) for t in nice if lo <= math.log10(t) <= hi] or [0.0]
    span = hi - lo
    step = 10 ** math.floor(math.log10(span / 3)) if span > 0 else 1
    for m in (1, 2, 5, 10):
        if span / (step * m) <= 6:
            step *= m
            break
    start = math.ceil(lo / step) * step
    out, t = [], start
    while t <= hi:
        out.append(round(t, 6))
        t += step
    return out or [0.0]


def _prediction_interval(meta, ratio) -> Optional[tuple]:
    pil, piu = getattr(meta, "pi_lower", None), getattr(meta, "pi_upper", None)
    if pil is not None and piu is not None:
        return pil, piu
    if (meta.pooled_estimate is None or meta.ci_lower is None
            or meta.tau_squared is None or (meta.k_studies or 0) < 3):
        return None
    mu = math.log(meta.pooled_estimate) if ratio else meta.pooled_estimate
    se = ((math.log(meta.pooled_estimate) - math.log(meta.ci_lower)) / 1.96
          if ratio else (meta.pooled_estimate - meta.ci_lower) / 1.96)
    sd = math.sqrt(max(meta.tau_squared, 0.0) + se ** 2)
    try:
        from scipy.stats import t as tdist
        tm = tdist.ppf(0.975, max(meta.k_studies - 2, 1))
    except Exception:
        tm = 2.0
    lo, hi = mu - tm * sd, mu + tm * sd
    return (math.exp(lo), math.exp(hi)) if ratio else (lo, hi)


def _het_line(meta):
    df = max((meta.k_studies or 1) - 1, 0)
    tau = f"$\\tau^2$ = {meta.tau_squared:.3f}" if meta.tau_squared is not None else "$\\tau^2$ = NA"
    q = f"Q = {meta.q_statistic:.2f}, df = {df}" if meta.q_statistic is not None else "Q = NA"
    ph = ""
    if meta.q_statistic is not None and df > 0:
        try:
            from scipy.stats import chi2
            ph = f" (P = {1 - chi2.cdf(meta.q_statistic, df):.3f})"
        except Exception:
            ph = ""
    i2 = f"$I^2$ = {meta.i_squared:.0f}%" if meta.i_squared is not None else "$I^2$ = NA"
    return f"Heterogeneity: {tau}; {q}{ph}; {i2}"


def _overall_effect_line(meta):
    if meta.p_value is None or meta.pooled_estimate is None or meta.ci_lower is None:
        return ""
    ratio = _ratio(meta.measure)
    mu = math.log(meta.pooled_estimate) if ratio else meta.pooled_estimate
    se = ((math.log(meta.pooled_estimate) - math.log(meta.ci_lower)) / 1.96
          if ratio else (meta.pooled_estimate - meta.ci_lower) / 1.96)
    z = mu / se if se else 0.0
    return f"Test for overall effect: Z = {z:.2f} (P = {meta.p_value:.3f})"


def _egger_line(est, se):
    import numpy as np
    if len(est) < 3:
        return None
    w = 1.0 / (se ** 2)
    X = np.vstack([np.ones_like(se), se]).T
    try:
        beta = np.linalg.solve(X.T @ (w[:, None] * X), X.T @ (w * est))
        return float(beta[0]), float(beta[1])
    except np.linalg.LinAlgError:
        return None


def save_meta_figures(meta: MetaAnalysisResult, outdir, *, treatment="", control="",
                      formats=("pdf", "png")) -> dict:
    import matplotlib.pyplot as plt
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    res = {"forest": [], "funnel": []}
    if meta and meta.forest:
        fig = build_forest_figure(meta, treatment=treatment, control=control)
        for fmt in formats:
            p = out / f"forest.{fmt}"
            fig.savefig(p, bbox_inches="tight", facecolor="white")
            res["forest"].append(p)
        plt.close(fig)
    if meta and meta.funnel and meta.pooled_estimate is not None:
        fig = build_funnel_figure(meta)
        for fmt in formats:
            p = out / f"funnel.{fmt}"
            fig.savefig(p, bbox_inches="tight", facecolor="white")
            res["funnel"].append(p)
        plt.close(fig)
    return res


def save_prisma_figure(flow: PrismaFlow, outdir, formats=("pdf", "png")) -> list:
    import matplotlib.pyplot as plt
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    fig = build_prisma_figure(flow)
    paths = []
    for fmt in formats:
        p = out / f"prisma_flow.{fmt}"
        fig.savefig(p, bbox_inches="tight", facecolor="white")
        paths.append(p)
    plt.close(fig)
    return paths
