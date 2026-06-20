"""Native, journal-grade PDF rendering via ReportLab (no LaTeX engine required).

Two-column layout with a full-width title block and abstract, serif body / sans
headings, "Figure N |" captions, and vector forest, funnel and PRISMA-flow
figures. This is the "open it anywhere" publication-style PDF; for a typeset
LaTeX PDF compile ``paper.tex`` instead.

Requires the optional dependency: ``pip install neuroaion[pdf]`` (reportlab).
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import Optional

from .models import MetaAnalysisResult, PrismaFlow, ReviewState

# Palette (restrained, journal-like).
INK = "#1a1a1a"
ACCENT = "#0b6e6e"      # teal section accent
MUTED = "#666666"
RULE = "#cfd8dc"
MARK = "#2b6cb0"


def _styles():
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
    from reportlab.lib import colors
    base = dict(fontName="Times-Roman", fontSize=8.6, leading=11.0,
                textColor=colors.HexColor(INK), alignment=TA_JUSTIFY, spaceAfter=4)
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=17,
                                 leading=20, textColor=colors.HexColor(INK), spaceAfter=6),
        "authors": ParagraphStyle("authors", fontName="Helvetica", fontSize=10,
                                   leading=13, textColor=colors.HexColor(INK), spaceAfter=2),
        "affil": ParagraphStyle("affil", fontName="Helvetica-Oblique", fontSize=8,
                                 leading=10, textColor=colors.HexColor(MUTED), spaceAfter=6),
        "abstract": ParagraphStyle("abstract", **{**base, "fontSize": 8.8, "leading": 11.6}),
        "h": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=9.4, leading=11.5,
                             textColor=colors.HexColor(ACCENT), spaceBefore=9, spaceAfter=2),
        "kw": ParagraphStyle("kw", fontName="Times-Roman", fontSize=7.8, leading=10,
                             textColor=colors.HexColor(INK), alignment=TA_JUSTIFY,
                             spaceBefore=3, spaceAfter=1),
        "h3": ParagraphStyle("h3", fontName="Helvetica-BoldOblique", fontSize=8.4,
                             leading=10.5, textColor=colors.HexColor(INK),
                             spaceBefore=6, spaceAfter=1),
        "body": ParagraphStyle("body", **base),
        "cap": ParagraphStyle("cap", fontName="Helvetica", fontSize=7.2, leading=9,
                               textColor=colors.HexColor(INK), alignment=TA_LEFT, spaceAfter=6),
        "muted": ParagraphStyle("muted", fontName="Helvetica", fontSize=7.2, leading=9,
                                textColor=colors.HexColor(MUTED), spaceAfter=4),
        "ref": ParagraphStyle("ref", fontName="Times-Roman", fontSize=7.4, leading=9.2,
                              textColor=colors.HexColor(INK), alignment=TA_LEFT, spaceAfter=2),
    }


def _para(text, style):
    from reportlab.platypus import Paragraph
    return Paragraph(text if "<" in (text or "") else html.escape(text or ""), style)


def _rich(markup, style):
    """A Paragraph from text that is ALREADY valid mini-XML markup — entities and
    tags are passed through verbatim (never re-escaped). Dynamic user-supplied
    substrings inside *markup* must be html.escaped by the caller."""
    from reportlab.platypus import Paragraph
    return Paragraph(markup or "", style)


def _caption(n, text, S):
    from reportlab.platypus import Paragraph
    return Paragraph(f"<b>Figure {n} |</b> {html.escape(text)}", S["cap"])


def _abstract_html(prose) -> str:
    """Render the abstract as HTML for a Paragraph — structured (bold run-in
    Background/Methods/Results/Conclusions) when a dict is supplied, else plain."""
    a = prose.get("abstract", "")
    if isinstance(a, dict):
        order = ["background", "methods", "results", "conclusions"]
        keys = [k for k in order if a.get(k)] + [k for k in a if k not in order and a.get(k)]
        return " ".join(f"<b>{k.capitalize()}.</b> {html.escape(str(a[k]).strip())}"
                        for k in keys)
    return html.escape(str(a or "").strip())


def _keywords(state) -> str:
    """A compact keyword line derived from the protocol (journals expect one)."""
    p = state.protocol
    kws = []
    for v in (p.pico.intervention, p.pico.outcome, p.pico.population):
        v = (v or "").split("(")[0].strip()
        if v:
            kws.append(v.lower())
    kws.append(f"{p.risk_of_bias.tool.lower()} risk of bias")
    kws.append("PRISMA 2020")
    # De-duplicate, keep order, cap at 6.
    seen, out = set(), []
    for k in kws:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return "; ".join(out[:6])


def _band_height(flowables, avail_w: float) -> float:
    """Total laid-out height of the title-block flowables (incl. inter-flow spacing)."""
    total = 0.0
    for f in flowables:
        try:
            _, h = f.wrap(avail_w, 1e6)
        except Exception:  # noqa: BLE001
            h = 0.0
        total += h
        st = getattr(f, "style", None)
        if st is not None:
            total += getattr(st, "spaceBefore", 0) + getattr(st, "spaceAfter", 0)
    return total


def _fit(drawing, target_w):
    """Scale a Drawing to a target width, preserving aspect ratio."""
    from reportlab.graphics.shapes import Drawing, Group
    if drawing is None or not drawing.width:
        return None
    s = target_w / drawing.width
    g = Group(*list(drawing.contents))
    g.transform = (s, 0, 0, s, 0, 0)
    d = Drawing(target_w, drawing.height * s)
    d.add(g)
    return d


# ── Figures (vector) ─────────────────────────────────────────────────────────
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
    pad = (hi - lo) * 0.12
    lo, hi = lo - pad, hi + pad
    GUT, PLOTW, RIGHT = 150, 230, 150
    step = 17
    n = len(rows)
    H = (n + 3) * step + 16
    d = Drawing(GUT + PLOTW + RIGHT, H)

    def X(v):
        return GUT + (v - lo) / (hi - lo) * PLOTW

    axis_y = 22
    top = axis_y + 2 * step
    d.add(Line(X(null), axis_y - 4, X(null), top + n * step, strokeColor=colors.HexColor("#999"),
               strokeDashArray=[3, 2]))
    d.add(Line(GUT, axis_y, GUT + PLOTW, axis_y, strokeColor=colors.HexColor(INK)))
    for tv in sorted({lo + pad, null, hi - pad}):
        d.add(String(X(tv), axis_y - 11, f"{tv:.2f}", fontSize=7, textAnchor="middle",
                     fontName="Helvetica"))
    for i, r in enumerate(rows):
        y = top + (n - 1 - i) * step
        x1, x2, xe = X(r["ci_lower"]), X(r["ci_upper"]), X(r["estimate"])
        sz = 2 + 4 * (r["weight_pct"] / 100.0)
        d.add(Line(x1, y, x2, y, strokeColor=colors.HexColor(INK)))
        d.add(Rect(xe - sz, y - sz, 2 * sz, 2 * sz, fillColor=colors.HexColor(MARK),
                   strokeColor=None))
        d.add(String(2, y - 3, r["study"][:30], fontSize=8, fontName="Helvetica"))
        d.add(String(GUT + PLOTW + 8, y - 3,
                     f"{r['estimate']:.2f} ({r['ci_lower']:.2f}, {r['ci_upper']:.2f})",
                     fontSize=8, fontName="Helvetica"))
    yp = top - step
    pe, pl, pu = X(meta.pooled_estimate), X(meta.ci_lower), X(meta.ci_upper)
    d.add(Polygon([pl, yp, pe, yp + 6, pu, yp, pe, yp - 6],
                  fillColor=colors.HexColor(INK), strokeColor=None))
    d.add(String(2, yp - 3, f"Pooled ({meta.model})", fontSize=8, fontName="Helvetica-Bold"))
    d.add(String(GUT + PLOTW + 8, yp - 3,
                 f"{meta.pooled_estimate:.2f} ({meta.ci_lower:.2f}, {meta.ci_upper:.2f})",
                 fontSize=8, fontName="Helvetica-Bold"))
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
    pad = (hi - lo) * 0.12
    lo, hi = lo - pad, hi + pad
    W, H, M = 340, 210, 34
    d = Drawing(W, H)

    def X(v):
        return M + (v - lo) / (hi - lo) * (W - 2 * M)

    def Y(se):
        return (H - M) - (se / max_se) * (H - 2 * M)

    apex = (X(pooled), Y(0))
    for sign in (-1, 1):
        d.add(Line(apex[0], apex[1], X(pooled + sign * 1.96 * max_se), Y(max_se),
                   strokeColor=colors.HexColor("#999"), strokeDashArray=[3, 2]))
    d.add(Line(X(pooled), Y(0), X(pooled), Y(max_se), strokeColor=colors.HexColor("#dddddd")))
    d.add(Line(M, Y(max_se), W - M, Y(max_se), strokeColor=colors.HexColor(INK)))
    for p in pts:
        d.add(Circle(X(p["estimate"]), Y(p["se"]), 3.2, fillColor=colors.HexColor(MARK),
                     strokeColor=None))
    d.add(String(W / 2, 6, meta.measure, fontSize=8, textAnchor="middle", fontName="Helvetica"))
    d.add(String(4, H - 11, "precision (1/SE)", fontSize=7.5, fontName="Helvetica"))
    return d


def _prisma_drawing(flow: PrismaFlow):
    from reportlab.graphics.shapes import Drawing, Rect, Line, String
    from reportlab.lib import colors
    rows = [
        ("Records identified", flow.records_total,
         ", ".join(f"{k}: {v}" for k, v in flow.records_identified.items())),
        ("Duplicates removed", flow.duplicates_removed, ""),
        ("Records screened", flow.records_screened, ""),
        ("Reports sought for retrieval", flow.reports_sought, ""),
        ("Reports assessed for eligibility", flow.reports_assessed, ""),
        ("Studies included", flow.studies_included, ""),
    ]
    side = {2: ("Excluded", flow.records_excluded_screening),
            3: ("Not retrieved", flow.reports_not_retrieved),
            4: ("Reports excluded", sum(flow.reports_excluded.values()))}
    W = 470
    bh, gap = 30, 13
    H = len(rows) * (bh + gap) + 6
    d = Drawing(W, H)
    bx, bw = 60, 250
    for i, (label, n, sub) in enumerate(rows):
        y = H - (i + 1) * (bh + gap) + gap
        d.add(Rect(bx, y, bw, bh, fillColor=colors.HexColor("#f3f6f6"),
                   strokeColor=colors.HexColor("#7a9a9a"), strokeWidth=0.7))
        d.add(String(bx + 8, y + bh - 12, f"{label}  (n = {n})", fontSize=8,
                     fontName="Helvetica-Bold"))
        if sub:
            d.add(String(bx + 8, y + 5, sub[:64], fontSize=6.4,
                         fillColor=colors.HexColor(MUTED), fontName="Helvetica"))
        if i < len(rows) - 1:
            d.add(Line(bx + bw / 2, y, bx + bw / 2, y - gap, strokeColor=colors.HexColor("#7a9a9a")))
        if i in side:
            lab, sn = side[i]
            sx = bx + bw + 36
            d.add(Rect(sx, y, 150, bh, fillColor=colors.white,
                       strokeColor=colors.HexColor("#b0bec5"), strokeWidth=0.7))
            d.add(String(sx + 6, y + bh / 2 - 3, f"{lab} (n = {sn})", fontSize=7,
                         fillColor=colors.HexColor(MUTED), fontName="Helvetica"))
            d.add(Line(bx + bw, y + bh / 2, sx, y + bh / 2, strokeColor=colors.HexColor("#b0bec5")))
    return d


_ROB_COLOR = {"low": "#2e7d32", "some concerns": "#f9a825", "high": "#c62828"}
_ROB_SYM = {"low": "+", "some concerns": "-", "high": "x"}


def _rob_traffic_drawing(state: ReviewState):
    """Cochrane-style risk-of-bias 'traffic-light' plot (compiled RoB)."""
    from reportlab.graphics.shapes import Drawing, Circle, String, Group
    from reportlab.lib import colors
    if not state.rob:
        return None
    domains = [d.name for d in state.rob[0].domains]
    cols = domains + ["Overall"]
    studies = state.rob
    cellw, cellh, labw, headh = 20, 17, 120, 78
    W = labw + len(cols) * cellw + 6
    H = headh + len(studies) * cellh + 6
    d = Drawing(W, H)
    # Rotated domain headers.
    for j, c in enumerate(cols):
        x = labw + j * cellw + cellw / 2
        g = Group(String(0, 0, (c[:20] + ("…" if len(c) > 20 else "")), fontSize=6.5,
                         fontName="Helvetica"))
        g.transform = (0, 1, -1, 0, x + 2, H - headh + 4)
        d.add(g)
    for i, a in enumerate(studies):
        y = H - headh - (i + 1) * cellh + cellh / 2
        d.add(String(2, y - 3, a.study_label[:24], fontSize=7, fontName="Helvetica"))
        jud = {dm.name: dm.judgement for dm in a.domains}
        for j, c in enumerate(cols):
            val = a.overall if c == "Overall" else jud.get(c, "some concerns")
            cx = labw + j * cellw + cellw / 2
            d.add(Circle(cx, y, 6, fillColor=colors.HexColor(_ROB_COLOR.get(val, "#9e9e9e")),
                         strokeColor=colors.white, strokeWidth=0.5))
            d.add(String(cx, y - 3, _ROB_SYM.get(val, "?"), fontSize=7, textAnchor="middle",
                         fillColor=colors.white, fontName="Helvetica-Bold"))
    return d


def _table(data, colw):
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    t = Table(data, repeatRows=1, hAlign="LEFT", colWidths=colw)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 6.8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(INK)),
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.HexColor(INK)),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor(INK)),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, colors.HexColor(INK)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2)]))
    return t


def _png_image(figdir, name, target_w):
    """A scaled Image flowable from a rendered matplotlib PNG, or None if absent."""
    if not figdir:
        return None
    from pathlib import Path as _P
    png = _P(figdir) / f"{name}.png"
    if not png.exists():
        return None
    try:
        from reportlab.platypus import Image
        from reportlab.lib.utils import ImageReader
        iw, ih = ImageReader(str(png)).getSize()
        if not iw:
            return None
        return Image(str(png), width=target_w, height=target_w * ih / iw)
    except Exception:  # noqa: BLE001
        return None


def build_pdf(state: ReviewState, prose: dict[str, str], path: str | Path,
              figdir: str | Path | None = None) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, FrameBreak,
                                    NextPageTemplate, Spacer, Table, TableStyle,
                                    KeepInFrame, HRFlowable)

    p = state.protocol
    s = state.synthesis
    meta = s.meta_analysis
    S = _styles()
    W, H = A4
    ml = mr = 1.6 * cm
    mt, mb = 1.5 * cm, 1.5 * cm
    gut = 0.75 * cm
    colw = (W - ml - mr - gut) / 2
    full_w = W - ml - mr

    # ── Title block (full width). Built first so we can size its band exactly. ──
    abstract_txt = prose.get("abstract", "") or (
        f"We systematically reviewed the effect of {p.pico.intervention} on "
        f"{p.pico.outcome}. {len(state.included_studies)} studies were included.")
    abs_inner = (_abstract_html(prose)
                 if isinstance(prose.get("abstract"), dict) else html.escape(str(abstract_txt)))
    abs_box = Table([[_rich(f"<b>Abstract</b>&#160;&#160;{abs_inner}", S["abstract"])]],
                    colWidths=[full_w])
    abs_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f7f8")),
        ("LINEABOVE", (0, 0), (-1, 0), 1.2, colors.HexColor(ACCENT)),
        ("LINEBELOW", (0, -1), (-1, -1), 0.4, colors.HexColor(RULE)),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))

    SEP = "&#160;&#160;&#183;&#160;&#160;"   # spaced middot separator
    _authors = ", ".join(p.authors) if p.authors else (p.authors_contact or "")
    title_block = [
        _para(p.title, S["title"]),
        _rich((f"<b>{html.escape(_authors)}</b>" if _authors else "")
              + (f"{SEP}{html.escape(p.affiliation)}" if p.affiliation else ""),
              S["authors"]),
        _rich("Systematic review and meta-analysis following PRISMA 2020"
              + (f"{SEP}{html.escape(p.registration)}" if p.registration else ""),
              S["affil"]),
        abs_box,
        _rich(f"<b>Keywords</b>&#160;&#160;{html.escape(_keywords(state))}", S["kw"]),
        _rich(f"<b>Review question</b>&#160;&#160;{html.escape(p.question)}", S["kw"]),
        HRFlowable(width="100%", thickness=0.8, color=colors.HexColor(ACCENT),
                   spaceBefore=4, spaceAfter=2),
    ]
    # Size the full-width band to exactly fit the title block (no overflow into
    # the body columns); clamp so at least a third of the page remains for columns.
    top_h = _band_height(title_block, full_w) + 6
    top_h = min(top_h, H - mt - mb - 9 * cm)

    # Frames: full-width title/abstract band, then two columns beneath it.
    top = Frame(ml, H - mt - top_h, full_w, top_h, id="top",
                leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=2)
    fc_l = Frame(ml, mb, colw, H - mt - top_h - mb, id="cl", leftPadding=0, rightPadding=7)
    fc_r = Frame(ml + colw + gut, mb, colw, H - mt - top_h - mb, id="cr",
                 leftPadding=7, rightPadding=0)
    col_l = Frame(ml, mb, colw, H - mt - mb, id="l", leftPadding=0, rightPadding=7)
    col_r = Frame(ml + colw + gut, mb, colw, H - mt - mb, id="r", leftPadding=7, rightPadding=0)

    short = (p.title[:78] + "…") if len(p.title) > 78 else p.title

    def header(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(ml, H - mt + 9, short)
        canvas.drawRightString(W - mr, H - mt + 9, f"{doc.page}")
        canvas.setStrokeColor(colors.HexColor(RULE))
        canvas.setLineWidth(0.5)
        canvas.line(ml, H - mt + 5, W - mr, H - mt + 5)
        canvas.restoreState()

    doc = BaseDocTemplate(str(path), pagesize=A4, title=p.title,
                          author=_authors or "", leftMargin=ml, rightMargin=mr,
                          topMargin=mt, bottomMargin=mb)
    doc.addPageTemplates([
        PageTemplate(id="first", frames=[top, fc_l, fc_r], onPage=header),
        PageTemplate(id="rest", frames=[col_l, col_r], onPage=header),
    ])

    story = list(title_block) + [NextPageTemplate("rest"), FrameBreak()]

    from reportlab.platypus import HRFlowable as _HR
    secn = [0]
    NUMBERED = {"Introduction", "Methods", "Results", "Discussion", "Conclusions"}

    def H2(t, numbered=None):
        from reportlab.lib import colors as _c
        num = numbered if numbered is not None else (t in NUMBERED)
        if num:
            secn[0] += 1
            label = f"{secn[0]}&#160;&#160;{html.escape(t.upper())}"
        else:
            label = html.escape(t.upper())
        story.append(_rich(label, S["h"]))
        story.append(_HR(width="100%", thickness=0.5, color=_c.HexColor(RULE),
                         spaceBefore=0, spaceAfter=3))

    def H3(t):
        # Subsection heading: numbered <main>.<n>, lighter, no rule.
        sub = getattr(H3, "_n", 0) + 1
        H3._n = sub
        story.append(_rich(f"{secn[0]}.{sub}&#160;&#160;{html.escape(t)}", S["h3"]))

    def _reset_sub():
        H3._n = 0

    fign = [0]

    def figure(drawing, caption, png_name=None):
        # Prefer the high-quality matplotlib PNG when it has been rendered into
        # the run directory; fall back to the native vector drawing otherwise.
        img = _png_image(figdir, png_name, colw) if png_name else None
        if img is None and drawing is None:
            return
        fign[0] += 1
        story.append(img if img is not None else _fit(drawing, colw))
        story.append(_caption(fign[0], caption, S))

    H2("Introduction")
    story.append(_para(prose.get("background", "") or
                       ("This review addresses: " + p.question), S["body"]))
    H2("Methods")
    story.append(_para(prose.get("methods", "") or
                       "Conducted and reported per PRISMA 2020.", S["body"]))
    story.append(_para(
        f"Two reviewers screened in duplicate (Cohen's κ = {state.cohen_kappa}); "
        f"conflicts were adjudicated. Risk of bias was appraised with "
        f"{html.escape(p.risk_of_bias.tool)} and certainty with GRADE. A "
        f"{html.escape(p.synthesis.model)}-effects inverse-variance model pooled "
        f"{html.escape(p.synthesis.effect_measure)} values; small-study effects were "
        f"examined with Egger's test and a funnel plot.", S["body"]))

    H2("Results")
    _reset_sub()
    H3("Study selection")
    figure(_prisma_drawing(state.prisma), "PRISMA 2020 study-selection flow diagram.",
           png_name="prisma_flow")
    if meta:
        story.append(_para(
            f"{len(state.included_studies)} studies were included. The pooled "
            f"{meta.measure} ({meta.model}-effects) was <b>{meta.pooled_estimate}</b> "
            f"(95% CI {meta.ci_lower} to {meta.ci_upper}; I&#178; = {meta.i_squared}%, "
            f"k = {meta.k_studies}). {html.escape(meta.interpretation)}", S["body"]))

    if state.extractions:
        rob_o = {r.uid: r.overall for r in state.rob}
        data = [["Study", "Design", "n", "RoB"]]
        for e in state.extractions:
            data.append([e.study_label, (e.design or "-")[:18], str(e.sample_size or "-"),
                         rob_o.get(e.uid, "-")])
        H3("Characteristics of included studies")
        story.append(_para("<b>Table 1 |</b> Characteristics of the included studies.", S["cap"]))
        story.append(_table(data, [colw * x for x in (0.42, 0.30, 0.12, 0.16)]))

    if state.rob:
        H3(f"Risk of bias ({state.rob[0].tool})")
        figure(_rob_traffic_drawing(state),
               "Risk-of-bias 'traffic-light' summary per study and domain "
               "(green/+ low, amber/- some concerns, red/x high).",
               png_name="rob_traffic")
        figure(None, "Risk-of-bias summary: distribution of judgements per domain "
               "across the included studies.", png_name="rob_summary")

    H3("Synthesis of results")
    figure(_forest_drawing(meta),
           f"Forest plot of {meta.measure if meta else 'effect'} estimates with the "
           f"{meta.model if meta else 'pooled'} summary (diamond) and 95% prediction "
           f"interval.", png_name="forest")
    story.append(_para(s.narrative, S["body"]))

    H3("Publication bias")
    figure(_funnel_drawing(meta), "Contour-enhanced funnel plot of effect size against "
           "standard error; shaded bands mark conventional significance contours and the "
           "dashed lines the pseudo-95% confidence funnel.", png_name="funnel")
    if meta and meta.eggers_p is not None:
        story.append(_para(
            f"Egger's regression test: intercept = {meta.eggers_intercept}, "
            f"p = {meta.eggers_p}, k = {meta.eggers_k}"
            + (" (under-powered: fewer than 10 studies)." if (meta.eggers_k or 0) < 10
               else "."), S["body"]))

    H3("Certainty of evidence (GRADE)")
    story.append(_para(f"<b>{html.escape(s.grade_certainty or 'not rated')}.</b> "
                       f"{html.escape(s.grade_rationale)}", S["body"]))
    H2("Discussion")
    story.append(_para(prose.get("discussion", ""), S["body"]))
    story.append(_para(f"<b>Limitations.</b> {html.escape(s.limitations)}", S["body"]))
    H2("Conclusions")
    story.append(_para(prose.get("conclusions", ""), S["body"]))

    # References (included studies).
    by_uid = {r.uid: r for r in state.unique_records}
    refs = [by_uid[u] for u in state.included_studies if u in by_uid]
    if refs:
        H2("References (included studies)")
        for i, r in enumerate(refs, 1):
            doi = f" https://doi.org/{r.doi}" if r.doi else ""
            story.append(_para(f"{i}. {html.escape(r.citation())}.{html.escape(doi)}", S["ref"]))

    doc.build(story)
    return Path(path)
