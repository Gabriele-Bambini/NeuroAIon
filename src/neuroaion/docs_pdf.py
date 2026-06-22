"""Compile the Markdown dossier (risk-of-bias worksheets, GRADE, checklists,
declarations, …) into polished PDF documents — the same way ``paper.pdf`` is
compiled from the review state.

A small, dependency-light Markdown renderer (headings, bold/italic/code/links,
tables, bullet lists, block quotes) turns each ``documents/*.md`` file into
ReportLab flowables; risk-of-bias judgements and signalling answers are
colour-coded. ``compile_dossier`` assembles the supplementary documents into a
single ``supplementary_materials.pdf`` and writes a standalone
``risk_of_bias.pdf`` for the appraisal worksheets.

Requires the optional ``reportlab`` dependency (``pip install neuroaion[pdf]``).
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from .models import ReviewState

INK, ACCENT, MUTED, RULE = "#1a1a1a", "#0b6e6e", "#666666", "#cfd8dc"
# Risk-of-bias / signalling-answer colour coding.
_LEVEL_BG = {
    "low": "#d8efdc", "low risk": "#d8efdc", "yes": "#d8efdc", "good": "#d8efdc",
    "some concerns": "#fdf0cf", "some concern": "#fdf0cf", "probably yes": "#eef3e6",
    "probably no": "#fbe9d8", "unclear": "#fdf0cf", "moderate": "#fdf0cf",
    "no information": "#eceff1", "fair": "#fdf0cf",
    "high": "#f7d7d7", "high risk": "#f7d7d7", "no": "#f7d7d7", "serious": "#f7d7d7",
    "critical": "#f7d7d7", "very high": "#f7d7d7", "poor": "#f7d7d7",
}


def _styles():
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
    from reportlab.lib import colors
    try:
        from .pdf_report import _serif
        SER = _serif()
    except Exception:  # noqa: BLE001
        SER = "Times-Roman"
    c = lambda h: colors.HexColor(h)  # noqa: E731
    return {
        "SER": SER,
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=14, leading=17,
                             textColor=c(INK), spaceBefore=4, spaceAfter=6),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=13,
                             textColor=c(ACCENT), spaceBefore=10, spaceAfter=3),
        "h3": ParagraphStyle("h3", fontName="Helvetica-BoldOblique", fontSize=9.6,
                             leading=12, textColor=c(INK), spaceBefore=7, spaceAfter=2),
        "body": ParagraphStyle("body", fontName=SER, fontSize=9.3, leading=12.6,
                               textColor=c(INK), alignment=TA_JUSTIFY, spaceAfter=5),
        "li": ParagraphStyle("li", fontName=SER, fontSize=9.3, leading=12.4,
                             textColor=c(INK), alignment=TA_LEFT, leftIndent=12,
                             bulletIndent=2, spaceAfter=2),
        "note": ParagraphStyle("note", fontName=SER, fontSize=9, leading=12,
                               textColor=c(MUTED), alignment=TA_LEFT, leftIndent=8,
                               spaceAfter=5),
        "cell": ParagraphStyle("cell", fontName=SER, fontSize=8.3, leading=10.6,
                               textColor=c(INK), alignment=TA_LEFT),
        "cellh": ParagraphStyle("cellh", fontName="Helvetica-Bold", fontSize=8.3,
                                leading=10.6, textColor=c(INK), alignment=TA_LEFT),
        "cap": ParagraphStyle("cap", fontName="Helvetica", fontSize=8, leading=10,
                              textColor=c(MUTED), spaceAfter=8),
    }


def _inline(text: str) -> str:
    """Markdown inline → ReportLab mini-XML (bold / italic / code / links)."""
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`(.+?)`", r'<font face="Courier" size="8">\1</font>', t)
    t = re.sub(r"(?<![\w*])_(?!_)(.+?)(?<!_)_(?![\w*])", r"<i>\1</i>", t)
    t = re.sub(r"\[(.+?)\]\((.+?)\)", r'<link href="\2" color="#0b6e6e">\1</link>', t)
    return t


def _cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def render_markdown(md: str, S=None, width: float = 460) -> list:
    """Parse a Markdown string into a list of ReportLab flowables."""
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, ListFlowable, ListItem
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    S = S or _styles()
    out: list = []
    lines = md.splitlines()
    i, n = 0, len(lines)
    bullets: list = []

    def flush_bullets():
        nonlocal bullets
        if bullets:
            out.append(ListFlowable([ListItem(Paragraph(_inline(b), S["li"]),
                                              leftIndent=12, value="•") for b in bullets],
                                    bulletType="bullet", start="•", leftIndent=10))
            bullets = []

    while i < n:
        raw = lines[i]
        line = raw.rstrip()
        st = line.strip()
        # Table: a run of pipe rows.
        if st.startswith("|") and "|" in st[1:]:
            tbl = []
            while i < n and lines[i].strip().startswith("|"):
                tbl.append(lines[i])
                i += 1
            flush_bullets()
            header = _cells(tbl[0])
            rows = [r for r in tbl[1:] if not re.match(r"^\s*\|?[\s:\-|]+\|?\s*$", r)]
            ncol = len(header)
            body_rows = [_cells(r) + [""] * ncol for r in rows]
            # Content-proportional column widths (handles 2-col label tables AND
            # wide GRADE/checklist tables) with a small per-column floor.
            maxlen = [1] * ncol
            for r in [header] + body_rows:
                for ci in range(ncol):
                    maxlen[ci] = max(maxlen[ci], len(re.sub(r"[*_`]", "", r[ci])))
            floor = 0.045
            raw = [max(floor, ml / sum(maxlen)) for ml in maxlen]
            sc = 1.0 / sum(raw)
            colw = [width * x * sc for x in raw]
            cell_sz = 7.0 if ncol >= 6 else 8.3
            cst = ParagraphStyle("c", parent=S["cell"], fontSize=cell_sz,
                                 leading=cell_sz * 1.25)
            chs = ParagraphStyle("ch", parent=S["cellh"], fontSize=cell_sz,
                                 leading=cell_sz * 1.25)
            pad = 3 if ncol < 6 else 2
            data = [[Paragraph(_inline(c), chs) for c in header]]
            styles = [("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.HexColor(INK)),
                      ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor(INK)),
                      ("LINEBELOW", (0, -1), (-1, -1), 0.8, colors.HexColor(INK)),
                      ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                      ("TOPPADDING", (0, 0), (-1, -1), pad),
                      ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
                      ("LEFTPADDING", (0, 0), (-1, -1), 4),
                      ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
            for ri, cs in enumerate(body_rows, 1):
                data.append([Paragraph(_inline(c), cst) for c in cs[:ncol]])
                for ci, cell in enumerate(cs[:ncol]):
                    bg = _LEVEL_BG.get(re.sub(r"[*_`]", "", cell).strip().lower())
                    if bg:
                        styles.append(("BACKGROUND", (ci, ri), (ci, ri), colors.HexColor(bg)))
            t = Table(data, colWidths=colw, repeatRows=1, hAlign="LEFT")
            t.setStyle(TableStyle(styles))
            out.append(t)
            out.append(Spacer(1, 6))
            continue
        if not st:
            flush_bullets()
            i += 1
            continue
        if st.startswith("### "):
            flush_bullets(); out.append(Paragraph(_inline(st[4:]), S["h3"]))
        elif st.startswith("## "):
            flush_bullets(); out.append(Paragraph(_inline(st[3:]), S["h2"]))
        elif st.startswith("# "):
            flush_bullets(); out.append(Paragraph(_inline(st[2:]), S["h1"]))
        elif st.startswith("> "):
            flush_bullets(); out.append(Paragraph(_inline(st[2:]), S["note"]))
        elif st.startswith(("- ", "* ")):
            bullets.append(st[2:])
        else:
            flush_bullets(); out.append(Paragraph(_inline(st), S["body"]))
        i += 1
    flush_bullets()
    return out


# ── Dossier assembly ─────────────────────────────────────────────────────────
def _doc(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return ""


def _build_pdf(out_path: Path, title: str, sections: list[tuple[str, str]]) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                    PageBreak, Spacer, HRFlowable)
    S = _styles()
    W, H = A4
    ml = mr = 2.0 * cm
    mt, mb = 1.7 * cm, 1.6 * cm
    cw = W - ml - mr
    short = (title[:90] + "…") if len(title) > 90 else title

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

    frame = Frame(ml, mb, cw, H - mt - mb, id="m", leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    doc = BaseDocTemplate(str(out_path), pagesize=A4, title=title,
                          leftMargin=ml, rightMargin=mr, topMargin=mt, bottomMargin=mb)
    doc.addPageTemplates([PageTemplate(id="m", frames=[frame], onPage=header)])

    story = [Paragraph(html.escape(title), S["h1"]),
             HRFlowable(width="100%", thickness=1.0, color=colors.HexColor(ACCENT),
                        spaceBefore=2, spaceAfter=8)]
    for idx, (_name, md) in enumerate(sections):
        if not md.strip():
            continue
        if idx > 0:
            story.append(PageBreak())
        story.extend(render_markdown(md, S, width=cw))
    doc.build(story)
    return out_path


# Order + friendly titles for the supplementary dossier.
_ORDER = [
    ("01_protocol.md", "Review protocol"),
    ("02_search_log.md", "Search log"),
    ("04_excluded_full_text.md", "Excluded full-text reports"),
    ("06_risk_of_bias.md", "Risk-of-bias assessment (overview)"),
    ("07_summary_of_findings.md", "GRADE Summary of Findings"),
    ("08_prisma_checklist.md", "PRISMA 2020 checklist"),
    ("08b_prisma_abstract_checklist.md", "PRISMA 2020 for Abstracts checklist"),
    ("09_method_comparison.md", "Method comparison"),
    ("10_declarations.md", "Declarations"),
    ("11_reporting_summary.md", "Reporting summary"),
]


def compile_dossier(out_dir: str | Path, state: ReviewState | None = None) -> dict:
    """Compile the Markdown dossier into PDFs. Returns the paths written.

    * ``documents/risk_of_bias.pdf``       — the completed RoB worksheets + summary.
    * ``documents/supplementary_materials.pdf`` — protocol, search log, GRADE,
      checklists, declarations, …
    Best-effort: returns {} if reportlab is unavailable.
    """
    try:
        import reportlab  # noqa: F401
    except Exception:  # noqa: BLE001
        return {}
    docs = Path(out_dir) / "documents"
    if not docs.exists():
        return {}
    written: dict[str, Path] = {}

    # 1) Risk of bias — the summary + every completed worksheet.
    rob_dir = docs / "rob_worksheets"
    rob_sections: list[tuple[str, str]] = []
    if (docs / "06_risk_of_bias.md").exists():
        rob_sections.append(("overview", _doc(docs / "06_risk_of_bias.md")))
    if rob_dir.exists():
        for f in sorted(rob_dir.glob("*.md")):
            rob_sections.append((f.stem, _doc(f)))
    if rob_sections:
        tool = state.protocol.risk_of_bias.tool if state else "RoB"
        written["risk_of_bias"] = _build_pdf(
            docs / "risk_of_bias.pdf", f"Risk-of-bias assessment ({tool})", rob_sections)

    # 2) Supplementary materials — the rest of the dossier.
    supp = [(title, _doc(docs / fn)) for fn, title in _ORDER if (docs / fn).exists()]
    if supp:
        written["supplementary"] = _build_pdf(
            docs / "supplementary_materials.pdf", "Supplementary materials", supp)
    return written
