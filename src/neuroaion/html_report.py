"""Self-contained HTML report — open in any browser, no LaTeX/Mermaid needed.

Renders the review as a single styled HTML file with inline SVG figures (PRISMA
flow, forest plot, funnel plot), so the result can be viewed with a double-click
on any desktop.
"""
from __future__ import annotations

import html as _h
from typing import Optional

from .models import MetaAnalysisResult, PrismaFlow, ReviewState


def esc(s: Optional[str]) -> str:
    return _h.escape(s or "")


def _forest_svg(meta: Optional[MetaAnalysisResult]) -> str:
    if not meta or not meta.forest:
        return "<p><em>Meta-analysis not performed.</em></p>"
    null = 1.0 if meta.measure.upper() in {"OR", "RR", "HR"} else 0.0
    rows = meta.forest
    vals = []
    for r in rows:
        vals += [r["ci_lower"], r["ci_upper"], r["estimate"]]
    vals += [meta.ci_lower or 0, meta.ci_upper or 0, meta.pooled_estimate or 0, null]
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        hi = lo + 1
    pad = (hi - lo) * 0.1
    lo, hi = lo - pad, hi + pad
    PLOT_L, PLOT_W = 230, 320          # label gutter, plot width
    RIGHT = PLOT_L + PLOT_W + 130
    rowh = 26
    H = (len(rows) + 3) * rowh

    def X(v):
        return PLOT_L + (v - lo) / (hi - lo) * PLOT_W

    s = [f'<svg viewBox="0 0 {RIGHT} {H}" width="100%" style="max-width:780px" '
         f'font-family="sans-serif" font-size="12">']
    xnull = X(null)
    s.append(f'<line x1="{xnull:.1f}" y1="10" x2="{xnull:.1f}" y2="{H-30:.1f}" '
             f'stroke="#bbb" stroke-dasharray="4"/>')
    for i, r in enumerate(rows):
        y = 20 + i * rowh
        x1, x2, xe = X(r["ci_lower"]), X(r["ci_upper"]), X(r["estimate"])
        sz = 3 + 6 * (r["weight_pct"] / 100.0)
        s.append(f'<line x1="{x1:.1f}" y1="{y}" x2="{x2:.1f}" y2="{y}" stroke="#333"/>')
        s.append(f'<rect x="{xe-sz:.1f}" y="{y-sz:.1f}" width="{2*sz:.1f}" '
                 f'height="{2*sz:.1f}" fill="#2b6cb0"/>')
        s.append(f'<text x="5" y="{y+4}">{esc(r["study"][:30])}</text>')
        s.append(f'<text x="{PLOT_L+PLOT_W+10}" y="{y+4}">'
                 f'{r["estimate"]:.2f} [{r["ci_lower"]:.2f}, {r["ci_upper"]:.2f}]</text>')
    # Pooled diamond.
    yp = 20 + len(rows) * rowh
    pe, pl, pu = X(meta.pooled_estimate), X(meta.ci_lower), X(meta.ci_upper)
    s.append(f'<polygon points="{pl:.1f},{yp} {pe:.1f},{yp-7} {pu:.1f},{yp} '
             f'{pe:.1f},{yp+7}" fill="#1a202c"/>')
    s.append(f'<text x="5" y="{yp+4}" font-weight="bold">Pooled ({esc(meta.model)})</text>')
    s.append(f'<text x="{PLOT_L+PLOT_W+10}" y="{yp+4}" font-weight="bold">'
             f'{meta.pooled_estimate:.2f} [{meta.ci_lower:.2f}, {meta.ci_upper:.2f}]</text>')
    # Axis.
    ay = yp + 20
    s.append(f'<line x1="{PLOT_L}" y1="{ay}" x2="{PLOT_L+PLOT_W}" y2="{ay}" stroke="#333"/>')
    for tv in sorted({lo + pad, null, hi - pad}):
        s.append(f'<text x="{X(tv):.1f}" y="{ay+14}" text-anchor="middle">{tv:.2f}</text>')
    s.append("</svg>")
    return "".join(s)


def _funnel_svg(meta: Optional[MetaAnalysisResult]) -> str:
    if not meta or not meta.funnel or meta.pooled_estimate is None:
        return "<p><em>Funnel plot unavailable.</em></p>"
    pts = meta.funnel
    max_se = max((p["se"] for p in pts), default=1.0) or 1.0
    pooled = meta.pooled_estimate
    xs = [p["estimate"] for p in pts] + [pooled - 1.96*max_se, pooled + 1.96*max_se]
    lo, hi = min(xs), max(xs)
    if hi <= lo:
        hi = lo + 1
    pad = (hi - lo) * 0.1
    lo, hi = lo - pad, hi + pad
    W, H, M = 420, 300, 40

    def X(v):
        return M + (v - lo) / (hi - lo) * (W - 2*M)

    def Y(se):
        return M + (se / max_se) * (H - 2*M)     # SE=0 top, max SE bottom

    s = [f'<svg viewBox="0 0 {W} {H+10}" width="100%" style="max-width:480px" '
         f'font-family="sans-serif" font-size="11">']
    apex = (X(pooled), Y(0))
    s.append(f'<line x1="{apex[0]:.1f}" y1="{apex[1]:.1f}" x2="{X(pooled-1.96*max_se):.1f}" '
             f'y2="{Y(max_se):.1f}" stroke="#bbb" stroke-dasharray="4"/>')
    s.append(f'<line x1="{apex[0]:.1f}" y1="{apex[1]:.1f}" x2="{X(pooled+1.96*max_se):.1f}" '
             f'y2="{Y(max_se):.1f}" stroke="#bbb" stroke-dasharray="4"/>')
    s.append(f'<line x1="{X(pooled):.1f}" y1="{M}" x2="{X(pooled):.1f}" y2="{H-M}" '
             f'stroke="#ddd"/>')
    for p in pts:
        s.append(f'<circle cx="{X(p["estimate"]):.1f}" cy="{Y(p["se"]):.1f}" r="3.5" '
                 f'fill="#2b6cb0"/>')
    s.append(f'<text x="{W/2:.0f}" y="{H-5}" text-anchor="middle">{esc(meta.measure)}</text>')
    s.append(f'<text x="10" y="{M-8}" >precision</text>')
    s.append("</svg>")
    return "".join(s)


def _prisma_html(flow: PrismaFlow) -> str:
    ident = "<br>".join(f"{esc(k)}: {v}" for k, v in flow.records_identified.items()) or "—"
    excl = sum(flow.reports_excluded.values())
    box = ("style=\"border:1px solid #888;border-radius:6px;padding:8px 10px;margin:6px auto;"
           "max-width:430px;text-align:center;background:#f7fafc\"")
    side = ("style=\"border:1px solid #aaa;border-radius:6px;padding:6px 8px;margin:6px auto;"
            "max-width:380px;text-align:center;background:#fff;color:#555;font-size:0.9em\"")
    arrow = '<div style="text-align:center;color:#888">↓</div>'
    return (
        f'<div {box}><b>Records identified</b> (n={flow.records_total})<br>{ident}</div>{arrow}'
        f'<div {box}><b>After duplicates removed</b> (n={flow.records_screened})<br>'
        f'<small>Duplicates removed: {flow.duplicates_removed}</small></div>{arrow}'
        f'<div {box}><b>Records screened</b> (n={flow.records_screened})</div>'
        f'<div {side}>Records excluded (n={flow.records_excluded_screening})</div>{arrow}'
        f'<div {box}><b>Reports sought</b> (n={flow.reports_sought})</div>'
        f'<div {side}>Not retrieved (n={flow.reports_not_retrieved})</div>{arrow}'
        f'<div {box}><b>Reports assessed</b> (n={flow.reports_assessed})</div>'
        f'<div {side}>Reports excluded (n={excl})</div>{arrow}'
        f'<div {box} ><b>Studies included</b> (n={flow.studies_included})</div>'
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


def build_html(state: ReviewState, prose: dict[str, str]) -> str:
    p = state.protocol
    s = state.synthesis
    meta = s.meta_analysis
    rob_overall = {r.uid: r.overall for r in state.rob}

    char_rows = [[e.study_label, e.design or "—", str(e.sample_size or "—"),
                  (e.population or "—")[:40], rob_overall.get(e.uid, "—")]
                 for e in state.extractions]
    rob_rows = []
    rob_head = ["Study"]
    if state.rob:
        rob_head += [d.name for d in state.rob[0].domains] + ["Overall"]
        for a in state.rob:
            jud = {d.name: d.judgement for d in a.domains}
            rob_rows.append([a.study_label] + [jud.get(d.name, "—") for d in state.rob[0].domains]
                            + [a.overall])
    forest_rows = [[f["study"], f"{f['estimate']:.2f}",
                    f"[{f['ci_lower']:.2f}, {f['ci_upper']:.2f}]", f"{f['weight_pct']:.1f}"]
                   for f in (meta.forest if meta else [])]

    meta_line = (f"Pooled {meta.measure} ({meta.model}-effects) = "
                 f"<b>{meta.pooled_estimate}</b> (95% CI {meta.ci_lower} to {meta.ci_upper}; "
                 f"I²={meta.i_squared}%, k={meta.k_studies})." if meta
                 else "Meta-analysis not performed.")
    pub = ("Egger's test: intercept="
           f"{meta.eggers_intercept}, p={meta.eggers_p}, k={meta.eggers_k}."
           if meta and meta.eggers_p is not None else "Not formally tested.")

    css = """body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:880px;
    margin:2rem auto;padding:0 1rem;color:#1a202c;line-height:1.5}
    h1{font-size:1.5rem}h2{border-bottom:2px solid #e2e8f0;padding-bottom:4px;margin-top:2rem}
    table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:0.9em}
    th,td{border:1px solid #cbd5e0;padding:5px 8px;text-align:left}
    th{background:#edf2f7}.banner{background:#fffbea;border:1px solid #f6e05e;padding:8px 12px;
    border-radius:6px}.fig{margin:1rem 0;padding:1rem;border:1px solid #e2e8f0;border-radius:8px}
    .muted{color:#718096;font-size:0.9em}"""

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(p.title)}</title><style>{css}</style></head><body>
<h1>{esc(p.title)}</h1>
<p class="muted">Generated by NeuroAIon · model: {esc(state.model)}
{' · (MOCK / illustrative)' if state.mock else ''}</p>
<p><b>Review question.</b> {esc(p.question)}</p>
<h2>Abstract</h2><p>{esc(prose.get('abstract','')) or meta_line}</p>
<h2>Background</h2><p>{esc(prose.get('background',''))}</p>
<h2>Methods</h2><p>{esc(prose.get('methods',''))}</p>
<p class="muted">Cohen's κ (inter-rater) = {state.cohen_kappa} · Risk-of-bias tool:
 {esc(p.risk_of_bias.tool)} · Effect measure: {esc(p.synthesis.effect_measure)}.</p>
<h2>Results</h2>
<h3>Study selection (PRISMA flow)</h3><div class="fig">{_prisma_html(state.prisma)}</div>
<p>{meta_line}</p>
<h3>Characteristics of included studies</h3>
{_table(["Study","Design","n","Population","RoB"], char_rows)}
<h3>Risk of bias</h3>{_table(rob_head, rob_rows) if rob_rows else '<p>—</p>'}
<h3>Forest plot</h3><div class="fig">{_forest_svg(meta)}</div>
{_table(["Study", p.synthesis.effect_measure, "95% CI", "Weight %"], forest_rows)}
<p>{esc(s.narrative)}</p>
<h3>Publication bias</h3><div class="fig">{_funnel_svg(meta)}</div><p>{pub}</p>
<h3>Certainty (GRADE)</h3><p><b>{esc(s.grade_certainty or 'not rated')}.</b>
 {esc(s.grade_rationale)}</p>
<h2>Discussion</h2><p>{esc(prose.get('discussion',''))}</p>
<p><b>Limitations.</b> {esc(s.limitations)}</p>
<h2>Conclusions</h2><p>{esc(prose.get('conclusions',''))}</p>
<hr><p class="muted">PRISMA 2020-compliant automated review. Artefacts: report.md,
 paper.tex (LaTeX→PDF), prospero_registration.md, state.json.</p>
</body></html>"""
