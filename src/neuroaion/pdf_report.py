"""Native, journal-grade PDF rendering via ReportLab (no LaTeX engine required).

Two-column layout with a full-width title block and abstract, serif body / sans
headings, "Figure N |" captions, and vector forest, funnel and PRISMA-flow
figures. This is the "open it anywhere" publication-style PDF; for a typeset
LaTeX PDF compile ``paper.tex`` instead.

Requires the optional dependency: ``pip install neuroaion[pdf]`` (reportlab).
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Optional

from .models import MetaAnalysisResult, PrismaFlow, ReviewState

# Palette (restrained, journal-like).
INK = "#1a1a1a"
ACCENT = "#0b6e6e"      # teal section accent
MUTED = "#666666"
RULE = "#cfd8dc"
MARK = "#2b6cb0"


_SERIF_CACHE = [None]


def _serif() -> str:
    """Register a Unicode serif (STIX — Times-like, full Greek/superscripts/math)
    so symbols such as I², τ², χ², ≤ and × render in body text. Falls back to the
    base-14 Times-Roman (no Greek) if the font files are unavailable."""
    if _SERIF_CACHE[0] is not None:
        return _SERIF_CACHE[0]
    fam = "Times-Roman"
    try:
        import os
        import matplotlib
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfbase.pdfmetrics import registerFontFamily
        fd = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf")
        for name, fn in (("STIX", "STIXGeneral.ttf"), ("STIX-Bold", "STIXGeneralBol.ttf"),
                         ("STIX-Italic", "STIXGeneralItalic.ttf"),
                         ("STIX-BoldItalic", "STIXGeneralBolIta.ttf")):
            pdfmetrics.registerFont(TTFont(name, os.path.join(fd, fn)))
        registerFontFamily("STIX", normal="STIX", bold="STIX-Bold",
                           italic="STIX-Italic", boldItalic="STIX-BoldItalic")
        fam = "STIX"
    except Exception:  # noqa: BLE001
        fam = "Times-Roman"
    _SERIF_CACHE[0] = fam
    return fam


def _styles():
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
    from reportlab.lib import colors
    SER = _serif()
    base = dict(fontName=SER, fontSize=9.2, leading=12.5,
                textColor=colors.HexColor(INK), alignment=TA_JUSTIFY, spaceAfter=6,
                firstLineIndent=0)
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=18,
                                 leading=21.5, textColor=colors.HexColor(INK), spaceAfter=7),
        "authors": ParagraphStyle("authors", fontName="Helvetica", fontSize=10.5,
                                   leading=14, textColor=colors.HexColor(INK), spaceAfter=2),
        "affil": ParagraphStyle("affil", fontName="Helvetica-Oblique", fontSize=8.4,
                                 leading=11, textColor=colors.HexColor(MUTED), spaceAfter=7),
        "abstract": ParagraphStyle("abstract", **{**base, "fontSize": 9.2, "leading": 12.8,
                                                   "spaceAfter": 4}),
        "h": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=11.5, leading=13.5,
                             textColor=colors.HexColor(ACCENT), spaceBefore=10, spaceAfter=3),
        "kw": ParagraphStyle("kw", fontName=SER, fontSize=8.6, leading=11.5,
                             textColor=colors.HexColor(INK), alignment=TA_JUSTIFY,
                             spaceBefore=3, spaceAfter=1),
        "h3": ParagraphStyle("h3", fontName="Helvetica-BoldOblique", fontSize=9.7,
                             leading=12, textColor=colors.HexColor(INK),
                             spaceBefore=8, spaceAfter=2),
        "h3full": ParagraphStyle("h3full", fontName="Helvetica-BoldOblique", fontSize=9.7,
                                 leading=12, textColor=colors.HexColor(INK),
                                 spaceBefore=10, spaceAfter=3),
        "body": ParagraphStyle("body", **base),
        "cap": ParagraphStyle("cap", fontName="Helvetica", fontSize=7.8, leading=10,
                               textColor=colors.HexColor(INK), alignment=TA_LEFT,
                               spaceBefore=3, spaceAfter=8),
        "muted": ParagraphStyle("muted", fontName="Helvetica", fontSize=7.6, leading=9.5,
                                textColor=colors.HexColor(MUTED), spaceAfter=4),
        "ref": ParagraphStyle("ref", fontName=SER, fontSize=8.3, leading=11,
                              textColor=colors.HexColor(INK), alignment=TA_LEFT, spaceAfter=3),
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


_ABS_LABELS = ["Background", "Objective", "Objectives", "Aim", "Aims", "Introduction",
               "Methods", "Data sources", "Results", "Findings", "Conclusion",
               "Conclusions", "Interpretation"]
_ABS_RE = re.compile(r"\s*\b(" + "|".join(_ABS_LABELS) + r")\b\s*[:.]\s+")


def _abstract_html(prose) -> str:
    """Render the abstract as HTML for a Paragraph: structured with bold run-in
    headers and a line break before each section (Background / Methods / Results /
    Conclusions), whether the abstract arrives as a dict or as a flat string."""
    a = prose.get("abstract", "")
    if isinstance(a, dict):
        order = ["background", "methods", "results", "conclusions"]
        keys = [k for k in order if a.get(k)] + [k for k in a if k not in order and a.get(k)]
        return "<br/>".join(f"<b>{k.capitalize()}.</b>&#160; {html.escape(str(a[k]).strip())}"
                            for k in keys)
    esc = html.escape(str(a or "").strip())
    out = _ABS_RE.sub(lambda m: f"<br/><b>{m.group(1)}.</b>&#160; ", esc)
    return out[len("<br/>"):] if out.startswith("<br/>") else out


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


def _png_image(figdir, name, target_w, max_h=None, align="CENTER"):
    """A scaled Image flowable from a rendered matplotlib PNG, or None if absent.

    Scales to *target_w*; if that would exceed *max_h* (a tall figure such as the
    risk-of-bias traffic light), it is scaled down to fit the page height instead.
    """
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
        w = target_w
        h = target_w * ih / iw
        if max_h and h > max_h:
            h = max_h
            w = h * iw / ih
        img = Image(str(png), width=w, height=h)
        img.hAlign = align
        return img
    except Exception:  # noqa: BLE001
        return None


def build_pdf(state: ReviewState, prose: dict[str, str], path: str | Path,
              figdir: str | Path | None = None) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Spacer,
                                    Table, TableStyle, HRFlowable, KeepTogether,
                                    BalancedColumns)

    p = state.protocol
    s = state.synthesis
    meta = s.meta_analysis
    S = _styles()
    W, H = A4
    ml = mr = 1.9 * cm
    mt, mb = 1.7 * cm, 1.7 * cm
    cw = W - ml - mr                       # full content width (spans both columns)
    GUT = 0.7 * cm                         # gutter between the two text columns

    # ── Title block ──────────────────────────────────────────────────────────
    abstract_txt = prose.get("abstract", "") or (
        f"We systematically reviewed the effect of {p.pico.intervention} on "
        f"{p.pico.outcome}. {len(state.included_studies)} studies were included.")
    abs_inner = (_abstract_html(prose) if prose.get("abstract")
                 else html.escape(str(abstract_txt)))
    abs_box = Table([[_rich(f"<b>Abstract</b>&#160;&#160;{abs_inner}", S["abstract"])]],
                    colWidths=[cw])
    abs_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f8f9")),
        ("LINEABOVE", (0, 0), (-1, 0), 1.4, colors.HexColor(ACCENT)),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor(RULE)),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))

    SEP = "&#160;&#160;&#183;&#160;&#160;"
    _authors = ", ".join(p.authors) if p.authors else (p.authors_contact or "")
    short = (p.title[:88] + "…") if len(p.title) > 88 else p.title

    def header(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(ml, H - mt + 10, short)
        canvas.drawRightString(W - mr, H - mt + 10, f"{doc.page}")
        canvas.setStrokeColor(colors.HexColor(RULE))
        canvas.setLineWidth(0.5)
        canvas.line(ml, H - mt + 6, W - mr, H - mt + 6)
        canvas.restoreState()

    frame = Frame(ml, mb, cw, H - mt - mb, id="main",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc = BaseDocTemplate(str(path), pagesize=A4, title=p.title, author=_authors or "",
                          leftMargin=ml, rightMargin=mr, topMargin=mt, bottomMargin=mb)
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=header)])

    story = [
        _para(p.title, S["title"]),
        _rich((f"<b>{html.escape(_authors)}</b>" if _authors else "")
              + (f"{SEP}{html.escape(p.affiliation)}" if p.affiliation else ""), S["authors"]),
        _rich("Systematic review and meta-analysis following PRISMA 2020"
              + (f"{SEP}{html.escape(p.registration)}" if p.registration else ""), S["affil"]),
        abs_box,
        _rich(f"<b>Keywords</b>&#160;&#160;{html.escape(_keywords(state))}", S["kw"]),
        _rich(f"<b>Review question</b>&#160;&#160;{html.escape(p.question)}", S["kw"]),
        HRFlowable(width="100%", thickness=1.0, color=colors.HexColor(ACCENT),
                   spaceBefore=6, spaceAfter=2),
    ]

    # ── Heading / figure builders (return flowables; placed by cols()/full()) ──
    secn, subn, fign = [0], [0], [0]
    NUMBERED = {"Introduction", "Methods", "Results", "Discussion", "Conclusions"}

    def h2(t, numbered=None):
        num = numbered if numbered is not None else (t in NUMBERED)
        if num:
            secn[0] += 1
            subn[0] = 0
            label = f"{secn[0]}&#160;&#160;{html.escape(t.upper())}"
        else:
            label = html.escape(t.upper())
        return [_rich(label, S["h"]),
                HRFlowable(width="100%", thickness=0.6, color=colors.HexColor(RULE),
                           spaceBefore=0, spaceAfter=5)]

    def h3(t, full=False):
        subn[0] += 1
        return [_rich(f"{secn[0]}.{subn[0]}&#160;&#160;{html.escape(t)}",
                      S["h3full"] if full else S["h3"])]

    max_fig_h = (H - mt - mb) - 64
    def fig_block(png_name, caption, drawing=None, frac=1.0):
        """A full-width figure (image scaled to *frac* of the page width, centred)
        kept together with its caption; returns the flowable or None."""
        img = _png_image(figdir, png_name, cw * frac, max_h=max_fig_h) if png_name else None
        if img is None and drawing is not None:
            img = _fit(drawing, cw * frac)
        if img is None:
            return None
        fign[0] += 1
        return KeepTogether([Spacer(1, 3), img, _caption(fign[0], caption, S), Spacer(1, 2)])

    # ── Flow control: 2-column text blocks interleaved with full-width floats ──
    buf: list = []

    def cols_flush():
        if buf:
            story.append(BalancedColumns(list(buf), nCols=2, innerPadding=GUT,
                                         leftPadding=0, rightPadding=0,
                                         topPadding=0, bottomPadding=0,
                                         spaceBefore=2, spaceAfter=6))
            buf.clear()

    def full(fl):
        cols_flush()
        if fl is None:
            return
        story.extend(fl if isinstance(fl, list) else [fl])

    def body(html_or_text, style="body"):
        return _para(html_or_text, S[style])

    # 2-column block 1 — Introduction, Methods, start of Results.
    buf += h2("Introduction")
    buf.append(body(prose.get("background", "") or ("This review addresses: " + p.question)))
    buf += h2("Methods")
    buf.append(body(prose.get("methods", "") or "Conducted and reported per PRISMA 2020."))
    buf.append(body(
        f"Two reviewers screened in duplicate (Cohen's κ = {state.cohen_kappa}); conflicts were "
        f"adjudicated. Risk of bias was appraised with {html.escape(p.risk_of_bias.tool)} and "
        f"certainty with GRADE. A {html.escape(p.synthesis.model)}-effects inverse-variance model "
        f"pooled {html.escape(p.synthesis.effect_measure)} values; small-study effects were "
        f"examined with Egger's test and a funnel plot."))
    buf += h2("Results")
    buf += h3("Study selection")
    if meta:
        buf.append(body(
            f"<b>{len(state.included_studies)} studies</b> were included. The pooled "
            f"{meta.measure} ({meta.model}-effects) was <b>{meta.pooled_estimate} "
            f"(95% CI {meta.ci_lower}&#8211;{meta.ci_upper})</b> (I&#178; = {meta.i_squared}%, "
            f"k = {meta.k_studies}). {html.escape(meta.interpretation)}"))
    cols_flush()

    # Full-width PRISMA flow.
    full(fig_block("prisma_flow", "PRISMA 2020 study-selection flow diagram.",
                   drawing=_prisma_drawing(state.prisma), frac=0.6))

    # Full-width characteristics table.
    if state.extractions:
        rob_o = {r.uid: r.overall for r in state.rob}
        data = [["Study", "Design", "n", "Risk of bias"]]
        for e in state.extractions:
            data.append([e.study_label, (e.design or "—")[:30], str(e.sample_size or "—"),
                         (rob_o.get(e.uid, "—") or "—").capitalize()])
        full(KeepTogether(h3("Characteristics of included studies", full=True) + [
              _para("<b>Table 1 |</b> Characteristics of the included studies.", S["cap"]),
              _table(data, [cw * x for x in (0.32, 0.36, 0.13, 0.19)])]))

    # Full-width risk-of-bias figures (heading kept with its plot, no orphans).
    if state.rob:
        traffic = fig_block("rob_traffic",
                            "Risk-of-bias 'traffic-light' summary per study and domain "
                            "(green, low; amber, some concerns; red, high risk).",
                            drawing=_rob_traffic_drawing(state), frac=0.98)
        full(KeepTogether(h3(f"Risk of bias ({state.rob[0].tool})", full=True)
                          + ([traffic] if traffic else [])))
        full(fig_block("rob_summary", "Risk-of-bias summary: distribution of judgements "
                       "per domain across the included studies.", frac=0.84))

    # 2-column synthesis narrative, then full-width forest.
    buf += h3("Synthesis of results")
    buf.append(body(s.narrative))
    cols_flush()
    full(fig_block("forest",
                   f"Forest plot of {meta.measure if meta else 'effect'} estimates with the "
                   f"{meta.model if meta else 'pooled'} summary (diamond) and 95% prediction "
                   f"interval.", drawing=_forest_drawing(meta), frac=1.0))

    # 2-column publication-bias text, then centred funnel.
    buf += h3("Publication bias")
    if meta and meta.eggers_p is not None:
        buf.append(body(
            f"Egger's regression test for small-study effects gave an intercept of "
            f"<b>{meta.eggers_intercept}</b> (p = {meta.eggers_p}, k = {meta.eggers_k})"
            + (", and is under-powered with fewer than 10 studies." if (meta.eggers_k or 0) < 10
               else ", indicating no significant funnel asymmetry.")))
    cols_flush()
    full(fig_block("funnel", "Contour-enhanced funnel plot of effect size against standard "
                   "error; shaded bands mark conventional significance contours and the dashed "
                   "lines the pseudo-95% confidence funnel.",
                   drawing=_funnel_drawing(meta), frac=0.56))

    # 2-column GRADE + Discussion + Conclusions + References.
    buf += h3("Certainty of evidence (GRADE)")
    buf.append(body(f"<b>{html.escape((s.grade_certainty or 'not rated').capitalize())}.</b> "
                    f"{html.escape(s.grade_rationale)}"))
    buf += h2("Discussion")
    buf.append(body(prose.get("discussion", "")))
    buf.append(body(f"<b>Limitations.</b> {html.escape(s.limitations)}"))
    buf += h2("Conclusions")
    buf.append(body(prose.get("conclusions", "")))
    cols_flush()        # close the GRADE/Discussion/Conclusions two-column block

    # References: a full-width heading, then the list balanced in two columns.
    by_uid = {r.uid: r for r in state.unique_records}
    refs = [by_uid[u] for u in state.included_studies if u in by_uid]
    if refs:
        full(h2("References (included studies)"))
        for i, r in enumerate(refs, 1):
            doi = f" https://doi.org/{r.doi}" if r.doi else ""
            buf.append(body(f"{i}.  {r.citation()}.{doi}", "ref"))
        cols_flush()

    doc.build(story)
    return Path(path)
