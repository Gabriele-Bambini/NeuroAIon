"""Native PDF rendering via ReportLab (no LaTeX engine required).

Produces a clean, multi-page PDF of the review — title, abstract, methods, a
drawn PRISMA flow diagram, characteristics and risk-of-bias tables, vector
forest and funnel plots, GRADE, discussion, conclusions. This is the "open it
anywhere" PDF; for the typeset LaTeX PDF compile ``paper.tex`` instead.

Requires the optional dependency: ``pip install neuroaion[pdf]`` (reportlab).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .models import MetaAnalysisResult, PrismaFlow, ReviewState


def _p(text: str, style):
    from reportlab.platypus import Paragraph
    import html
    return Paragraph(html.escape(text or ""), style)


def _forest_drawing(meta: Optional[MetaAnalysisResult]):
    from reportlab.graphics.shapes import Drawing, Line, Rect, Polygon, String
    from reportlab.lib import colors
    if not meta or not meta.forest:
        return None
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
    GUT, PLOTW, RIGHT = 120, 190, 110
    step = 16
    n = len(rows)
    H = (n + 3) * step + 20
    d = Drawing(GUT + PLOTW + RIGHT, H)

    def X(v):
        return GUT + (v - lo) / (hi - lo) * PLOTW

    axis_y = 24
    top = axis_y + 2 * step
    d.add(Line(X(null), axis_y - 4, X(null), top + n * step, strokeColor=colors.grey,
               strokeDashArray=[3, 2]))
    d.add(Line(GUT, axis_y, GUT + PLOTW, axis_y, strokeColor=colors.black))
    for tv in sorted({lo + pad, null, hi - pad}):
        d.add(String(X(tv), axis_y - 12, f"{tv:.2f}", fontSize=7, textAnchor="middle"))
    for i, r in enumerate(rows):
        y = top + (n - 1 - i) * step
        x1, x2, xe = X(r["ci_lower"]), X(r["ci_upper"]), X(r["estimate"])
        sz = 1.8 + 3.5 * (r["weight_pct"] / 100.0)
        d.add(Line(x1, y, x2, y, strokeColor=colors.black))
        d.add(Rect(xe - sz, y - sz, 2 * sz, 2 * sz, fillColor=colors.HexColor("#2b6cb0"),
                   strokeColor=None))
        d.add(String(4, y - 3, r["study"][:26], fontSize=7))
        d.add(String(GUT + PLOTW + 6, y - 3,
                     f"{r['estimate']:.2f} [{r['ci_lower']:.2f}, {r['ci_upper']:.2f}]",
                     fontSize=7))
    yp = top - step
    pe, pl, pu = X(meta.pooled_estimate), X(meta.ci_lower), X(meta.ci_upper)
    d.add(Polygon([pl, yp, pe, yp + 5, pu, yp, pe, yp - 5],
                  fillColor=colors.HexColor("#1a202c"), strokeColor=None))
    d.add(String(4, yp - 3, f"Pooled ({meta.model})", fontSize=7, fontName="Helvetica-Bold"))
    d.add(String(GUT + PLOTW + 6, yp - 3,
                 f"{meta.pooled_estimate:.2f} [{meta.ci_lower:.2f}, {meta.ci_upper:.2f}]",
                 fontSize=7, fontName="Helvetica-Bold"))
    return d


def _funnel_drawing(meta: Optional[MetaAnalysisResult]):
    from reportlab.graphics.shapes import Drawing, Line, Circle, String
    from reportlab.lib import colors
    if not meta or not meta.funnel or meta.pooled_estimate is None:
        return None
    pts = meta.funnel
    max_se = max((p["se"] for p in pts), default=1.0) or 1.0
    pooled = meta.pooled_estimate
    xs = [p["estimate"] for p in pts] + [pooled - 1.96 * max_se, pooled + 1.96 * max_se]
    lo, hi = min(xs), max(xs)
    if hi <= lo:
        hi = lo + 1
    pad = (hi - lo) * 0.1
    lo, hi = lo - pad, hi + pad
    W, H, M = 300, 200, 30
    d = Drawing(W, H)

    def X(v):
        return M + (v - lo) / (hi - lo) * (W - 2 * M)

    def Y(se):                       # SE=0 at top, max SE at bottom
        return (H - M) - (se / max_se) * (H - 2 * M)

    apex = (X(pooled), Y(0))
    d.add(Line(apex[0], apex[1], X(pooled - 1.96 * max_se), Y(max_se),
               strokeColor=colors.grey, strokeDashArray=[3, 2]))
    d.add(Line(apex[0], apex[1], X(pooled + 1.96 * max_se), Y(max_se),
               strokeColor=colors.grey, strokeDashArray=[3, 2]))
    d.add(Line(X(pooled), Y(0), X(pooled), Y(max_se), strokeColor=colors.HexColor("#ddd")))
    for p in pts:
        d.add(Circle(X(p["estimate"]), Y(p["se"]), 3, fillColor=colors.HexColor("#2b6cb0"),
                     strokeColor=None))
    d.add(String(W / 2, 6, meta.measure, fontSize=8, textAnchor="middle"))
    d.add(String(2, H - 12, "precision", fontSize=8))
    return d


def _prisma_drawing(flow: PrismaFlow):
    from reportlab.graphics.shapes import Drawing, Rect, Line, String
    from reportlab.lib import colors
    rows = [
        ("Records identified", flow.records_total,
         ", ".join(f"{k}:{v}" for k, v in flow.records_identified.items())),
        ("After duplicates removed", flow.records_screened,
         f"duplicates removed: {flow.duplicates_removed}"),
        ("Records screened", flow.records_screened, ""),
        ("Reports sought", flow.reports_sought, ""),
        ("Reports assessed", flow.reports_assessed, ""),
        ("Studies included", flow.studies_included, ""),
    ]
    side = {2: ("excluded", flow.records_excluded_screening),
            3: ("not retrieved", flow.reports_not_retrieved),
            4: ("reports excluded", sum(flow.reports_excluded.values()))}
    W = 460
    bh, gap = 34, 14
    H = len(rows) * (bh + gap) + 10
    d = Drawing(W, H)
    bx, bw = 70, 230
    for i, (label, n, sub) in enumerate(rows):
        y = H - (i + 1) * (bh + gap) + gap
        d.add(Rect(bx, y, bw, bh, fillColor=colors.HexColor("#f7fafc"),
                   strokeColor=colors.HexColor("#888")))
        d.add(String(bx + 8, y + bh - 13, f"{label} (n={n})", fontSize=8,
                     fontName="Helvetica-Bold"))
        if sub:
            d.add(String(bx + 8, y + 6, sub[:60], fontSize=6.5,
                         fillColor=colors.HexColor("#555")))
        if i < len(rows) - 1:
            d.add(Line(bx + bw / 2, y, bx + bw / 2, y - gap, strokeColor=colors.grey))
        if i in side:
            lab, sn = side[i]
            sx = bx + bw + 30
            d.add(Rect(sx, y, 150, bh, fillColor=colors.white,
                       strokeColor=colors.HexColor("#aaa")))
            d.add(String(sx + 6, y + bh / 2 - 3, f"{lab} (n={sn})", fontSize=7,
                         fillColor=colors.HexColor("#555")))
            d.add(Line(bx + bw, y + bh / 2, sx, y + bh / 2, strokeColor=colors.grey))
    return d


def build_pdf(state: ReviewState, prose: dict[str, str], path: str | Path) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Spacer, Table, TableStyle)
    from reportlab.lib import colors

    p = state.protocol
    s = state.synthesis
    meta = s.meta_analysis
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1b", parent=styles["Title"], fontSize=15, leading=18)
    h2 = ParagraphStyle("h2b", parent=styles["Heading2"], fontSize=11, spaceBefore=10)
    body = ParagraphStyle("bodyb", parent=styles["BodyText"], fontSize=9.5, leading=13)
    muted = ParagraphStyle("muted", parent=body, fontSize=8, textColor=colors.grey)

    story = [_p(p.title, h1),
             _p(f"NeuroAIon · model: {state.model}"
                + (" · MOCK / illustrative" if state.mock else ""), muted),
             _p(f"<b>Review question.</b> {p.question}", body), Spacer(1, 6)]

    def section(title, text):
        story.append(_p(title, h2))
        if text:
            story.append(_p(text, body))

    section("Abstract", prose.get("abstract", ""))
    section("Background", prose.get("background", ""))
    section("Methods", prose.get("methods", ""))
    story.append(_p(f"Cohen's &#954; = {state.cohen_kappa} · RoB tool: {p.risk_of_bias.tool} "
                    f"· effect measure: {p.synthesis.effect_measure}.", muted))

    story.append(_p("Results — study selection (PRISMA)", h2))
    pf = _prisma_drawing(state.prisma)
    if pf:
        story.append(pf)
    meta_line = (f"Pooled {meta.measure} ({meta.model}-effects) = {meta.pooled_estimate} "
                 f"(95% CI {meta.ci_lower} to {meta.ci_upper}; I-squared={meta.i_squared}%, "
                 f"k={meta.k_studies})." if meta else "Meta-analysis not performed.")
    story.append(_p(meta_line, body))

    # Characteristics table.
    if state.extractions:
        rob_o = {r.uid: r.overall for r in state.rob}
        data = [["Study", "Design", "n", "Population", "RoB"]]
        for e in state.extractions:
            data.append([e.study_label, e.design or "-", str(e.sample_size or "-"),
                         (e.population or "-")[:26], rob_o.get(e.uid, "-")])
        story.append(_p("Characteristics of included studies", h2))
        story.append(_mktable(data, Table, TableStyle, colors))

    # Forest.
    story.append(_p("Forest plot", h2))
    fd = _forest_drawing(meta)
    if fd:
        story.append(fd)
    story.append(_p(s.narrative, body))

    # Funnel + bias.
    story.append(_p("Publication bias", h2))
    fn = _funnel_drawing(meta)
    if fn:
        story.append(fn)
    if meta and meta.eggers_p is not None:
        story.append(_p(f"Egger's test: intercept={meta.eggers_intercept}, "
                        f"p={meta.eggers_p}, k={meta.eggers_k}.", body))

    section("Certainty (GRADE)",
            f"{s.grade_certainty or 'not rated'}. {s.grade_rationale}")
    section("Discussion", prose.get("discussion", ""))
    story.append(_p(f"<b>Limitations.</b> {s.limitations}", body))
    section("Conclusions", prose.get("conclusions", ""))

    out = Path(path)
    SimpleDocTemplate(str(out), pagesize=A4, topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                      leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                      title=p.title).build(story)
    return out


def _mktable(data, Table, TableStyle, colors):
    t = Table(data, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf2f7")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t
