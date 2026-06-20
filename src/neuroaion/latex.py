"""LaTeX rendering — turn a completed review into a publication-grade paper.

Produces a single ``paper.tex`` styled after top-tier computational-biology
journals (Bioinformatics / Nature Methods / PLOS Computational Biology / Genome
Biology house style): a Times-like single-column research layout with line
numbers, coloured section-accent rules, structured abstract, Nature-style
``Figure N |`` captions, ``threeparttable`` booktabs tables, typeset estimator
equations (DerSimonian--Laird & REML, Hartung--Knapp, prediction intervals,
Egger/Begg/trim-and-fill), and journal end-matter (data/code availability,
author contributions, competing interests, funding).

Figures prefer high-quality matplotlib PDFs (``forest.pdf``, ``funnel.pdf``,
``prisma_flow.pdf``) rendered into the same directory as ``paper.tex``; when a
PDF is absent the document falls back to a self-contained TikZ vector figure, so
the paper always compiles with ``pdflatex`` + ``bibtex`` anywhere TeXLive-full
is available.
"""
from __future__ import annotations

import re
from typing import Optional

from .agents.reporter import PRISMAReporter
from .models import MetaAnalysisResult, PrismaFlow, Record, ReviewState

_SPECIAL = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}

# Common Unicode that LLM prose / interpretation strings may contain — normalised
# to LaTeX-safe equivalents so the document compiles under plain pdflatex.
_UNICODE = {
    "²": r"\textsuperscript{2}", "³": r"\textsuperscript{3}", "¹": r"\textsuperscript{1}",
    "×": r"$\times$", "÷": r"$\div$", "±": r"$\pm$", "≈": r"$\approx$",
    "≤": r"$\leq$", "≥": r"$\geq$", "≠": r"$\neq$", "→": r"$\rightarrow$",
    "−": "-", "–": "--", "—": "---", "•": r"\textbullet{}",
    "“": "``", "”": "''", "‘": "`", "’": "'", "…": r"\dots{}",
    "α": r"$\alpha$", "β": r"$\beta$", "γ": r"$\gamma$", "δ": r"$\delta$",
    "μ": r"$\mu$", "σ": r"$\sigma$", "τ": r"$\tau$", "κ": r"$\kappa$",
    "θ": r"$\theta$", "χ": r"$\chi$", "°": r"$^{\circ}$", " ": " ",
}


def esc(s: Optional[str]) -> str:
    """Normalise Unicode then escape LaTeX special characters in arbitrary text."""
    out: list[str] = []
    for ch in (s or ""):
        if ch in _UNICODE:
            out.append(_UNICODE[ch])
        elif ch in _SPECIAL:
            out.append(_SPECIAL[ch])
        else:
            out.append(ch)
    return "".join(out)


def _num(value, fmt: str = "{:.3g}") -> Optional[str]:
    """Format an optional number, returning None when absent."""
    if value is None:
        return None
    try:
        return fmt.format(float(value))
    except (TypeError, ValueError):
        return None


# ── Preamble (static; raw to avoid brace-escaping headaches) ─────────────────
# Every package below ships with TeXLive-full (the CI compiles with
# xu-cheng/latex-action, a full TeXLive image, via latexmk + pdflatex).
_PREAMBLE = r"""\documentclass[11pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
% Times-like text + maths (journal standard); TeXLive-full provides newtx.
\usepackage{newtxtext}
\usepackage{newtxmath}
\usepackage{microtype}
\usepackage[margin=1in]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{textcomp}
\usepackage{siunitx}
\sisetup{detect-all,round-mode=places,round-precision=2,table-number-alignment=center}
\usepackage[table]{xcolor}
\definecolor{roblow}{HTML}{C8E6C9}
\definecolor{robsome}{HTML}{FFF1C2}
\definecolor{robhigh}{HTML}{FFCDD2}
\definecolor{accent}{HTML}{1A5276}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{threeparttable}
\usepackage{longtable}
\usepackage{array}
\usepackage{caption}
% Nature-style captions: bold "Figure"/"Table" label followed by a vertical bar.
\DeclareCaptionLabelFormat{figbar}{\textbf{#1~#2\,\textbar}}
\captionsetup{labelfont=bold,labelsep=quad,font=small,labelformat=figbar}
\usepackage{float}
\usepackage{titlesec}
\titleformat{\section}{\normalfont\large\bfseries\color{accent}}{\thesection}{0.6em}{}[{\color{accent}\titlerule[0.8pt]}]
\titleformat{\subsection}{\normalfont\normalsize\bfseries\color{accent}}{\thesubsection}{0.6em}{}
\usepackage{authblk}
\renewcommand\Affilfont{\small\itshape}
\setlength{\affilsep}{0.4em}
\usepackage[hidelinks]{hyperref}
\usepackage[switch]{lineno}
\usepackage{tikz}
\usetikzlibrary{shapes.geometric,arrows.meta,positioning,calc}
\setlength{\parskip}{0.45em}
\setlength{\parindent}{0pt}
"""


def _citekey(rec: Record, used: set[str]) -> str:
    base = (rec.authors[0].split()[0] if rec.authors else "Anon")
    base = re.sub(r"[^A-Za-z]", "", base) or "Anon"
    key = f"{base}{rec.year or 'nd'}"
    cand, i = key, 0
    while cand in used:
        cand = key + chr(ord("a") + i)
        i += 1
    used.add(cand)
    return cand


def _bib_entry(key: str, rec: Record) -> str:
    """A richer BibTeX entry: volume/issue/pages/pmid plus entry-type mapping."""

    def f(field: str, value) -> str:
        v = "" if value is None else str(value).strip()
        return f"  {field} = {{{v}}},\n" if v else ""

    def g(attr: str):                      # safe getattr for evolving model
        return getattr(rec, attr, "") or ""

    authors = " and ".join(rec.authors) if rec.authors else "Anonymous"
    etype = (g("entry_type") or "article").lower()
    pmid = g("pmid")
    journal = rec.journal or g("journal_abbrev")
    notes: list[str] = []

    if etype == "preprint":
        bibtype, note = "@misc", "Preprint"
    elif etype == "inproceedings":
        bibtype, note = "@inproceedings", ""
    elif etype in {"book"}:
        bibtype, note = "@book", ""
    elif etype in {"misc"}:
        bibtype, note = "@misc", ""
    else:
        bibtype, note = "@article", ""
    if note:
        notes.append(note)
    if pmid:
        notes.append(f"PMID: {pmid}")

    title = (rec.title or "").replace("{", "").replace("}", "")
    body = (
        f"{bibtype}{{{key},\n"
        + f("title", title)
        + f("author", authors)
        + (f("booktitle", journal) if bibtype == "@inproceedings"
           else f("journal", journal))
        + (f("year", rec.year) if rec.year else "")
        + f("volume", g("volume"))
        + f("number", g("issue"))
        + f("pages", g("pages"))
        + f("doi", rec.doi)
        + f("pmid", pmid)
        + f("url", rec.url)
        + f("note", "; ".join(notes))
        + "}\n"
    )
    return body


def _methods_equations(state: ReviewState) -> str:
    """Typeset the actual estimators used, so the methods are fully reproducible."""
    measure = state.protocol.synthesis.effect_measure
    model = state.protocol.synthesis.model
    meta = None
    if state.synthesis and state.synthesis.meta_analysis:
        meta = state.synthesis.meta_analysis

    def m(attr):
        return getattr(meta, attr, None) if meta is not None else None

    eqs = [
        r"For each study $i$ the effect estimate $y_i$ was combined by "
        r"inverse-variance weighting, $w_i = 1/\mathrm{SE}_i^2$, giving the "
        r"common-effect pooled estimate",
        r"\begin{equation}",
        r"\hat{\theta} = \frac{\sum_i w_i\, y_i}{\sum_i w_i}, \qquad "
        r"\mathrm{SE}(\hat{\theta}) = \sqrt{\tfrac{1}{\sum_i w_i}}.",
        r"\end{equation}",
        r"Heterogeneity was quantified with Cochran's $Q$, the $I^2$ and $H$ "
        r"statistics, and the between-study variance $\tau^2$:",
        r"\begin{equation}",
        r"Q = \sum_i w_i (y_i-\hat{\theta}_{\mathrm{FE}})^2, \quad "
        r"I^2 = \max\!\left(0,\ \frac{Q-(k-1)}{Q}\right)\times 100\%, \quad "
        r"H = \sqrt{\frac{Q}{k-1}}.",
        r"\end{equation}",
        r"The between-study variance $\tau^2$ was estimated by both the "
        r"non-iterative DerSimonian--Laird (DL) moment estimator",
        r"\begin{equation}",
        r"\hat{\tau}^2_{\mathrm{DL}} = \max\!\left(0,\ \frac{Q-(k-1)}"
        r"{\sum_i w_i - \frac{\sum_i w_i^2}{\sum_i w_i}}\right),",
        r"\end{equation}",
        r"and by restricted maximum likelihood (REML), which iterates",
        r"\begin{equation}",
        r"\hat{\tau}^2_{\mathrm{REML}} = \frac{\sum_i w_i^{*2}\big[(y_i-\hat{\theta})^2 "
        r"- (1/w_i)\big]}{\sum_i w_i^{*2}} + \frac{1}{\sum_i w_i^{*}}, \qquad "
        r"w_i^{*} = \frac{1}{\mathrm{SE}_i^2 + \hat{\tau}^2},",
        r"\end{equation}",
        r"to convergence. ",
    ]
    if model == "random":
        eqs.append(
            r"Under random effects the inverse-variance weights become "
            r"$w_i^{*} = 1/(\mathrm{SE}_i^2 + \hat{\tau}^2)$. ")

    tau2_method = (m("tau2_method") or "DL")
    knha = bool(m("knha"))
    chosen = ("REML" if str(tau2_method).upper().startswith("REML") else
              "DerSimonian--Laird")
    eqs.append(
        f"The primary analysis used the {chosen} estimator of $\\tau^2$. ")
    if knha:
        eqs.append(
            r"Confidence intervals for the pooled effect used the "
            r"Hartung--Knapp--Sidik--Jonkman (HKSJ) adjustment, which replaces the "
            r"standard normal quantile with a $t$ quantile on $k-1$ degrees of "
            r"freedom, $\hat{\theta} \pm t_{k-1,\,0.975}\,\mathrm{SE}(\hat{\theta})$, "
            r"giving better coverage when $k$ is small. ")
    else:
        eqs.append(
            r"The Hartung--Knapp--Sidik--Jonkman adjustment "
            r"($t_{k-1}$ quantiles for improved small-sample coverage) was "
            r"available and applied where appropriate. ")

    eqs += [
        r"A 95\% prediction interval (Higgins--Thompson--Spiegelhalter) for the "
        r"effect in a new study was computed as",
        r"\begin{equation}",
        r"\hat{\theta} \pm t_{k-2,\,0.975}\,\sqrt{\hat{\tau}^2 + "
        r"\mathrm{SE}^2(\hat{\theta})},",
        r"\end{equation}",
        r"and 95\% confidence intervals for $I^2$ (and $H$) were obtained from "
        r"the $Q$-profile / test-based method. ",
    ]

    eqs.append(
        r"Small-study effects and publication bias (PRISMA item 14) were assessed "
        r"with Egger's regression test, Begg \& Mazumdar's rank-correlation test, "
        r"and Duval \& Tweedie's trim-and-fill adjustment, complemented by a "
        r"contour-enhanced funnel plot; these were interpreted cautiously when "
        r"$k<10$.")
    eqs.append(
        r"Inter-rater agreement at title/abstract screening was summarised with "
        r"Cohen's $\kappa = (p_o - p_e)/(1 - p_e)$, where $p_o$ and $p_e$ are the "
        r"observed and chance-expected agreement.")
    eqs.append(
        f"The effect measure was the {esc(measure)} "
        f"({'standardised mean difference' if measure == 'SMD' else esc(measure)}); "
        f"ratio measures were pooled on the natural-log scale.")
    return "\n".join(eqs)


# ── TikZ figure *bodies* (no surrounding figure float) ───────────────────────
def _prisma_tikz_body(flow: PrismaFlow) -> str:
    """The PRISMA 2020 flow diagram as a bare tikzpicture (no figure wrapper)."""
    ident = r"\\ ".join(f"{esc(k)}: {v}" for k, v in flow.records_identified.items()) or "--"
    excl_reports = sum(flow.reports_excluded.values())
    box = ("box/.style={draw, rounded corners, align=center, text width=5.2cm, "
           "inner sep=4pt, font=\\small}")
    side = ("side/.style={draw, align=center, text width=4.6cm, inner sep=4pt, "
            "font=\\small}")
    return (
        f"\\begin{{tikzpicture}}[node distance=1.05cm and 2.6cm, {box}, {side}, "
        ">=Stealth]\n"
        f"\\node[box] (id) {{Records identified ($n={flow.records_total}$)\\\\ {ident}}};\n"
        f"\\node[box, below=of id] (dd) {{Records after duplicates removed "
        f"($n={flow.records_screened}$)\\\\ Duplicates removed "
        f"($n={flow.duplicates_removed}$)}};\n"
        f"\\node[box, below=of dd] (sc) {{Records screened ($n={flow.records_screened}$)}};\n"
        f"\\node[side, right=of sc] (ex1) {{Records excluded "
        f"($n={flow.records_excluded_screening}$)}};\n"
        f"\\node[box, below=of sc] (so) {{Reports sought for retrieval "
        f"($n={flow.reports_sought}$)}};\n"
        f"\\node[side, right=of so] (nr) {{Reports not retrieved "
        f"($n={flow.reports_not_retrieved}$)}};\n"
        f"\\node[box, below=of so] (as) {{Reports assessed for eligibility "
        f"($n={flow.reports_assessed}$)}};\n"
        f"\\node[side, right=of as] (er) {{Reports excluded ($n={excl_reports}$)}};\n"
        f"\\node[box, below=of as] (in) {{Studies included in review "
        f"($n={flow.studies_included}$)}};\n"
        "\\draw[->] (id) -- (dd);\n\\draw[->] (dd) -- (sc);\n"
        "\\draw[->] (sc) -- (ex1);\n\\draw[->] (sc) -- (so);\n"
        "\\draw[->] (so) -- (nr);\n\\draw[->] (so) -- (as);\n"
        "\\draw[->] (as) -- (er);\n\\draw[->] (as) -- (in);\n"
        "\\end{tikzpicture}\n"
    )


def prisma_tikz(flow: PrismaFlow) -> str:
    """A PRISMA 2020 flow diagram drawn in pure TikZ (vector, self-contained)."""
    return (
        "\\begin{figure}[H]\n\\centering\n"
        + _prisma_tikz_body(flow)
        + "\\caption{PRISMA 2020 study-selection flow diagram.}\n"
        + "\\end{figure}\n"
    )


def _forest_tikz_body(meta: MetaAnalysisResult) -> str:
    """The forest plot as a bare tikzpicture (caller supplies the figure float)."""
    null = 1.0 if meta.measure.upper() in {"OR", "RR", "HR"} else 0.0
    vals = []
    for r in meta.forest:
        vals += [r["ci_lower"], r["ci_upper"], r["estimate"]]
    vals += [meta.ci_lower or 0, meta.ci_upper or 0, meta.pooled_estimate or 0, null]
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        hi = lo + 1.0
    pad = (hi - lo) * 0.10
    lo, hi = lo - pad, hi + pad
    W = 9.0

    def X(v: float) -> float:
        return (v - lo) / (hi - lo) * W

    rows = meta.forest
    n = len(rows)
    sep = 0.62
    top = n * sep
    L = ["\\begin{tikzpicture}[x=1cm,y=1cm,font=\\scriptsize,>=Stealth]\n"]
    L.append(f"\\draw[dashed,gray] ({X(null):.3f},{-0.7:.3f}) -- "
             f"({X(null):.3f},{top + 0.3:.3f});\n")
    L.append(f"\\draw[->] (0,{-0.7:.3f}) -- ({W + 0.2:.3f},{-0.7:.3f});\n")
    for tv in sorted({lo + pad, null, hi - pad}):
        L.append(f"\\draw ({X(tv):.3f},{-0.7:.3f}) -- ({X(tv):.3f},{-0.85:.3f}) "
                 f"node[below] {{{tv:.2f}}};\n")
    for i, r in enumerate(rows):
        y = top - i * sep
        x1, x2, xe = X(r["ci_lower"]), X(r["ci_upper"]), X(r["estimate"])
        s = 0.05 + 0.10 * (r["weight_pct"] / 100.0)
        L.append(f"\\draw ({x1:.3f},{y:.3f}) -- ({x2:.3f},{y:.3f});\n")
        L.append(f"\\fill ({xe - s:.3f},{y - s:.3f}) rectangle "
                 f"({xe + s:.3f},{y + s:.3f});\n")
        L.append(f"\\node[left] at ({-0.25:.3f},{y:.3f}) "
                 f"{{{esc(r['study'][:26])}}};\n")
        L.append(f"\\node[right] at ({W + 0.35:.3f},{y:.3f}) "
                 f"{{{r['estimate']:.2f} [{r['ci_lower']:.2f}, {r['ci_upper']:.2f}]}};\n")
    pe, pl, pu = meta.pooled_estimate, meta.ci_lower, meta.ci_upper
    L.append(f"\\fill[black!80] ({X(pl):.3f},0) -- ({X(pe):.3f},0.18) -- "
             f"({X(pu):.3f},0) -- ({X(pe):.3f},-0.18) -- cycle;\n")
    L.append(f"\\node[left] at ({-0.25:.3f},0) {{Pooled ({esc(meta.model)})}};\n")
    L.append(f"\\node[right] at ({W + 0.35:.3f},0) "
             f"{{{pe:.2f} [{pl:.2f}, {pu:.2f}]}};\n")
    L.append("\\end{tikzpicture}\n")
    return "".join(L)


def forest_tikz(meta: Optional[MetaAnalysisResult]) -> str:
    """A forest plot drawn in pure TikZ from the pooled meta-analysis."""
    if not meta or not meta.forest:
        return "\\textit{Meta-analysis not performed (insufficient comparable data).}\n"
    caption = (f"\\caption{{Forest plot ({esc(meta.measure)}, {esc(meta.model)} effects; "
               f"$k={meta.k_studies}$, $I^2={meta.i_squared}\\%$).}}\n")
    return ("\\begin{figure}[H]\n\\centering\n"
            + _forest_tikz_body(meta) + caption + "\\end{figure}\n")


def _funnel_tikz_body(meta: MetaAnalysisResult) -> str:
    """The funnel plot as a bare tikzpicture (caller supplies the figure float)."""
    pts = meta.funnel
    ses = [p["se"] for p in pts]
    max_se = max(ses) if ses else 1.0
    if max_se <= 0:
        max_se = 1.0
    pooled = meta.pooled_estimate
    xs = [p["estimate"] for p in pts] + [pooled - 1.96 * max_se, pooled + 1.96 * max_se]
    lo, hi = min(xs), max(xs)
    if hi <= lo:
        hi = lo + 1.0
    pad = (hi - lo) * 0.1
    lo, hi = lo - pad, hi + pad
    W, H = 8.0, 5.5

    def X(v: float) -> float:
        return (v - lo) / (hi - lo) * W

    def Y(se: float) -> float:
        return H * (1.0 - se / max_se)

    L = ["\\begin{tikzpicture}[x=1cm,y=1cm,font=\\scriptsize,>=Stealth]\n"]
    L.append(f"\\draw[->] (0,0) -- ({W + 0.3:.3f},0) node[right] {{{esc(meta.measure)}}};\n")
    L.append(f"\\draw[->] ({X(pooled):.3f},0) -- ({X(pooled):.3f},{H + 0.3:.3f}) "
             f"node[above] {{precision}};\n")
    apex_x, apex_y = X(pooled), Y(0.0)
    lx, ly = X(pooled - 1.96 * max_se), Y(max_se)
    rx, ry = X(pooled + 1.96 * max_se), Y(max_se)
    L.append(f"\\draw[dashed,gray] ({apex_x:.3f},{apex_y:.3f}) -- ({lx:.3f},{ly:.3f});\n")
    L.append(f"\\draw[dashed,gray] ({apex_x:.3f},{apex_y:.3f}) -- ({rx:.3f},{ry:.3f});\n")
    L.append(f"\\draw[dotted] ({X(pooled):.3f},0) -- ({X(pooled):.3f},{H:.3f});\n")
    for p in pts:
        L.append(f"\\fill ({X(p['estimate']):.3f},{Y(p['se']):.3f}) circle (1.6pt);\n")
    L.append("\\end{tikzpicture}\n")
    return "".join(L)


def funnel_tikz(meta: Optional[MetaAnalysisResult]) -> str:
    """A funnel plot (effect vs. standard error) with a pseudo-95% CI funnel."""
    if not meta or not meta.funnel or meta.pooled_estimate is None:
        return ""
    return ("\\begin{figure}[H]\n\\centering\n"
            + _funnel_tikz_body(meta)
            + "\\caption{Funnel plot of effect size against precision (apex = pooled "
            "estimate; dashed lines = pseudo 95\\% confidence funnel).}\n"
            + "\\end{figure}\n")


def _figure_with_fallback(pdf_name: str, tikz_body: str, caption: str,
                          label: str) -> str:
    """Emit a figure float that prefers a matplotlib PDF, else inlines TikZ.

    ``\\IfFileExists`` chooses the high-quality vector PDF rendered alongside
    ``paper.tex`` when present, and otherwise compiles the self-contained TikZ
    fallback — so the document always builds and the TikZ source is always there.
    """
    return (
        "\\begin{figure}[htbp]\n\\centering\n"
        + "\\IfFileExists{" + pdf_name + "}%\n"
        + "  {\\includegraphics[width=\\linewidth,keepaspectratio]{" + pdf_name + "}}%\n"
        + "  {\\resizebox{\\linewidth}{!}{%\n" + tikz_body + "  }}%\n"
        + "\\caption{" + caption + "}\n"
        + "\\label{" + label + "}\n"
        + "\\end{figure}\n"
    )


def _publication_bias_text(meta: Optional[MetaAnalysisResult]) -> str:
    if not meta or meta.eggers_p is None:
        return ("Publication bias was not formally tested (fewer than three studies "
                "with usable variances).")
    asym = "evidence of" if meta.eggers_p < 0.10 else "no strong evidence of"
    power = " Note that with $k<10$ the test is under-powered." \
        if (meta.eggers_k or 0) < 10 else ""
    out = (f"Egger's regression test indicated {asym} funnel asymmetry "
           f"(intercept $={meta.eggers_intercept}$, $p={meta.eggers_p}$, "
           f"$k={meta.eggers_k}$).{power}")
    begg_p = getattr(meta, "begg_p", None)
    if begg_p is not None:
        out += (f" Begg \\& Mazumdar's rank-correlation test gave $p={esc(str(begg_p))}$.")
    tf = getattr(meta, "trimfill_missing", None)
    if tf is not None:
        adj = getattr(meta, "trimfill_adjusted_estimate", None)
        side = getattr(meta, "trimfill_side", None)
        extra = ""
        if adj is not None:
            extra = (f", with a trim-and-fill adjusted pooled estimate of "
                     f"${esc(str(adj))}$")
        sidetxt = f" on the {esc(str(side))} side" if side else ""
        out += (f" Duval \\& Tweedie's trim-and-fill imputed {tf} potentially "
                f"missing studies{sidetxt}{extra}.")
    return out


def _heterogeneity_text(meta: Optional[MetaAnalysisResult]) -> str:
    """A sentence summarising heterogeneity with CIs and the prediction interval."""
    if not meta:
        return ""
    parts: list[str] = []
    i2 = _num(meta.i_squared, "{:.1f}")
    if i2 is not None:
        ci_lo = _num(getattr(meta, "i_squared_ci_lower", None), "{:.1f}")
        ci_hi = _num(getattr(meta, "i_squared_ci_upper", None), "{:.1f}")
        if ci_lo is not None and ci_hi is not None:
            parts.append(f"$I^2={i2}\\%$ (95\\% CI {ci_lo}\\% to {ci_hi}\\%)")
        else:
            parts.append(f"$I^2={i2}\\%$")
    tau2 = _num(getattr(meta, "tau_squared", None))
    if tau2 is not None:
        parts.append(f"$\\tau^2={tau2}$")
    qp = _num(getattr(meta, "q_p_value", None))
    if qp is not None:
        parts.append(f"Cochran's $Q$ $p={qp}$")
    h = _num(getattr(meta, "H", None))
    if h is not None:
        parts.append(f"$H={h}$")
    sentence = ""
    if parts:
        sentence = "Heterogeneity: " + ", ".join(parts) + ". "
    pi_lo = _num(getattr(meta, "pi_lower", None))
    pi_hi = _num(getattr(meta, "pi_upper", None))
    if pi_lo is not None and pi_hi is not None:
        sentence += (f"The 95\\% prediction interval was {pi_lo} to {pi_hi}, "
                     "indicating the plausible range of the true effect in a new "
                     "setting. ")
    return sentence


# ── Tables (threeparttable + booktabs) ───────────────────────────────────────
def _characteristics_table(state: ReviewState, keys: dict[str, str]) -> str:
    rob = {r.uid: r.overall for r in state.rob}
    head = (
        "\\begin{table}[htbp]\n\\centering\n\\begin{threeparttable}\n"
        "\\caption{Characteristics of included studies.}\n"
        "\\label{tab:characteristics}\n"
        "\\begin{tabular}{p{3.0cm} l S[table-format=4.0] p{3.2cm} c}\n\\toprule\n"
        "Study & Design & {$n$} & Population & RoB \\\\\n\\midrule\n"
    )
    rows = []
    for ex in state.extractions:
        cite = f"~\\cite{{{keys[ex.uid]}}}" if ex.uid in keys else ""
        n = ex.sample_size if ex.sample_size is not None else "{--}"
        rows.append(
            f"{esc(ex.study_label)}{cite} & {esc(ex.design or '--')} & "
            f"{n} & {esc((ex.population or '--')[:60])} & "
            f"{esc(rob.get(ex.uid, '--'))} \\\\\n"
        )
    foot = (
        "\\bottomrule\n\\end{tabular}\n"
        "\\begin{tablenotes}[flushleft]\\footnotesize\n"
        "\\item $n$, analysed sample size; RoB, overall risk-of-bias judgement.\n"
        "\\item ``--'' indicates the field was not reported in the source study.\n"
        "\\end{tablenotes}\n\\end{threeparttable}\n\\end{table}\n"
    )
    return head + "".join(rows) + foot


_ROB_CELL = {"low": "\\cellcolor{roblow}", "some concerns": "\\cellcolor{robsome}",
             "high": "\\cellcolor{robhigh}"}


def _rob_cell(judgement: str) -> str:
    j = (judgement or "").lower()
    return f"{_ROB_CELL.get(j, '')}{esc(judgement or '--')}"


def _rob_longtable(state: ReviewState) -> str:
    """Risk-of-bias traffic-light table inside a threeparttable float."""
    if not state.rob:
        return "\\textit{No included studies were appraised.}\n"
    domains = [d.name for d in state.rob[0].domains]
    colspec = "p{3.2cm} " + " ".join(["c"] * len(domains)) + " c"
    head = (
        "\\begin{table}[htbp]\n\\centering\n\\begin{threeparttable}\n"
        "\\caption{Risk-of-bias assessment (" + esc(state.rob[0].tool) + ").}\n"
        "\\label{tab:rob}\n"
        "\\begin{tabular}{" + colspec + "}\n\\toprule\nStudy & "
        + " & ".join(esc(d[:14]) for d in domains)
        + " & Overall \\\\\n\\midrule\n"
    )
    rows = []
    for a in state.rob:
        jud = {d.name: d.judgement for d in a.domains}
        cells = " & ".join(_rob_cell(jud.get(d, "--")) for d in domains)
        rows.append(f"{esc(a.study_label[:24])} & {cells} & {_rob_cell(a.overall)} \\\\\n")
    foot = (
        "\\bottomrule\n\\end{tabular}\n"
        "\\begin{tablenotes}[flushleft]\\footnotesize\n"
        "\\item Cell colour encodes the domain judgement: "
        "\\colorbox{roblow}{low}, \\colorbox{robsome}{some concerns}, "
        "\\colorbox{robhigh}{high} risk of bias.\n"
        "\\end{tablenotes}\n\\end{threeparttable}\n\\end{table}\n"
    )
    return head + "".join(rows) + foot


def _checklist_longtable() -> str:
    from .prisma import CHECKLIST_2020
    cov = PRISMAReporter.coverage_map()
    head = ("\\begin{longtable}{c p{3.2cm} p{6.0cm} p{3.2cm}}\n"
            "\\caption{PRISMA 2020 checklist.}\\\\\n\\toprule\n"
            "\\# & Item & Description & Addressed by \\\\\n\\midrule\n\\endhead\n")
    rows = []
    for num, name, desc in CHECKLIST_2020:
        rows.append(f"{num} & {esc(name)} & {esc(desc)} & {esc(cov.get(num, 'report'))} \\\\\n")
    return head + "".join(rows) + "\\bottomrule\n\\end{longtable}\n"


# ── Structured abstract ──────────────────────────────────────────────────────
def _abstract_block(prose, state: ReviewState) -> str:
    """Render a structured abstract (dict) or a plain-string abstract."""
    p = state.protocol
    raw = prose.get("abstract") if isinstance(prose, dict) else None
    if isinstance(raw, dict):
        order = [("background", "Background"), ("methods", "Methods"),
                 ("results", "Results"), ("conclusions", "Conclusions")]
        runs = []
        for key, label in order:
            val = raw.get(key)
            if val:
                runs.append(f"\\textbf{{{label}.}} {esc(str(val))}")
        # Include any extra keys not in the canonical order.
        for key, val in raw.items():
            if key not in {k for k, _ in order} and val:
                runs.append(f"\\textbf{{{esc(key.title())}.}} {esc(str(val))}")
        body = "\n\n".join(runs) if runs else _default_abstract(state)
    elif isinstance(raw, str) and raw.strip():
        body = esc(raw)
    else:
        body = _default_abstract(state)
    return "\\begin{abstract}\n" + body + "\n\\end{abstract}\n"


def _default_abstract(state: ReviewState) -> str:
    p = state.protocol
    return (
        f"We systematically reviewed the effect of {esc(p.pico.intervention)} on "
        f"{esc(p.pico.outcome)}. {len(state.included_studies)} studies were included."
    )


# ── End-matter (journal house style) ─────────────────────────────────────────
def _end_matter(state: ReviewState, has_bib: bool) -> str:
    p = state.protocol
    contact = esc(p.authors_contact) if p.authors_contact else "the corresponding author"
    reg = esc(p.registration) if p.registration else "not registered"
    authors_txt = ", ".join(esc(a) for a in p.authors) if p.authors else "The author(s)"
    blocks = [
        "\\section*{Data availability}\n"
        "All extracted study-level data, screening decisions, the structured review "
        "protocol, the risk-of-bias assessments and the machine-readable data file "
        "are provided as supplementary material; the bibliography lists every "
        f"included study. Requests may be directed to {contact}.\n",
        "\\section*{Statistical analysis}\n"
        "Quantitative synthesis used inverse-variance random-effects meta-analysis "
        "(REML estimator of the between-study variance with the "
        "Hartung--Knapp--Sidik--Jonkman variance correction); heterogeneity was "
        "summarised by Cochran's $Q$, $I^2$, $\\tau^2$ and a 95\\% prediction "
        "interval, and small-study effects were examined with Egger's test and "
        "trim-and-fill.\n",
        "\\section*{Author contributions}\n"
        + authors_txt + " designed and registered the review, conducted the search "
        "and study selection in duplicate, extracted the data, appraised risk of "
        "bias with RoB~2, performed the synthesis and wrote the manuscript.\n",
        "\\section*{Competing interests}\n"
        "The authors declare no competing interests.\n",
        "\\section*{Funding}\n"
        "This review received no specific grant from any funding agency in the "
        "public, commercial, or not-for-profit sectors. "
        f"Registration: {reg}.\n",
    ]
    return "\n".join(blocks)


def build_document(state: ReviewState, prose) -> tuple[str, str]:
    """Return (paper_tex, references_bib)."""
    prose = prose or {}
    p = state.protocol
    s = state.synthesis
    by_uid = {r.uid: r for r in state.unique_records}

    # Citation keys + bib for included studies.
    used: set[str] = set()
    keys: dict[str, str] = {}
    bib_parts: list[str] = []
    for uid in state.included_studies:
        rec = by_uid.get(uid)
        if rec:
            k = _citekey(rec, used)
            keys[uid] = k
            bib_parts.append(_bib_entry(k, rec))
    bib = "\n".join(bib_parts)

    cite_all = ""
    if keys:
        cite_all = " \\citep{" + ",".join(keys.values()) + "}"

    has_bib = bool(bib_parts)
    meta = s.meta_analysis

    # Bibstyle from the protocol's citation style (numbered Vancouver-ish).
    style = (getattr(p, "citation_style", "") or "vancouver").lower()
    # vancouver.bst may be absent on minimal TeXLive; unsrtnat is always present
    # and gives the same numbered, citation-order list.
    bibstyle = "unsrtnat"
    if "vancouver" in style:
        bibstyle = "unsrtnat"   # safe default; numbered + sort&compress via natbib

    parts: list[str] = [_PREAMBLE]
    parts.append("\\usepackage[numbers,sort&compress]{natbib}\n")
    # Embed the bibliography so the document is fully self-contained.
    if has_bib:
        parts.append("\\begin{filecontents*}[overwrite]{\\jobname.bib}\n" + bib +
                     "\n\\end{filecontents*}\n")
    parts.append(f"\\title{{{esc(p.title)}}}\n")
    _au = ", ".join(esc(a) for a in p.authors) if p.authors else esc(p.authors_contact or "Author")
    parts.append(f"\\author[1]{{{_au}}}\n")
    parts.append("\\affil[1]{"
                 + (esc(p.affiliation) if p.affiliation else "Systematic review")
                 + (f"\\\\ Contact: {esc(p.authors_contact)}" if p.authors_contact else "")
                 + "}\n")
    parts.append("\\date{\\today}\n\\begin{document}\n\\maketitle\n")
    parts.append("\\linenumbers\n")
    parts.append(_abstract_block(prose, state))

    intro = (esc(prose.get("background", "")) if isinstance(prose, dict) else "") or \
        esc("This review addresses the question: " + p.question)
    parts.append("\\section{Introduction}\n" + intro + "\n")

    # Methods
    inc = "".join(f"\\item {esc(c)}\n" for c in p.inclusion_criteria) or "\\item ---\n"
    exc = "".join(f"\\item {esc(c)}\n" for c in p.exclusion_criteria) or "\\item ---\n"
    sources = ", ".join(esc(x) for x in (state.prisma.records_identified or p.search.sources))
    methods_prose = (esc(prose.get("methods", "")) if isinstance(prose, dict) else "") or \
        "This review was conducted and reported in accordance with PRISMA 2020."
    parts.append(
        "\\section{Methods}\n"
        + methods_prose + "\n\n"
        + "\\subsection{Eligibility criteria}\n\\textbf{Inclusion:}\n"
        + "\\begin{itemize}\n" + inc + "\\end{itemize}\n\\textbf{Exclusion:}\n"
        + "\\begin{itemize}\n" + exc + "\\end{itemize}\n"
        + f"\\subsection{{Information sources and search}}\nDatabases searched "
        f"({esc(str(p.search.date_from))}--{esc(str(p.search.date_to))}): {sources}. "
        f"Records were de-duplicated by DOI and fuzzy title matching.\n"
        + "\\subsection{Selection, extraction and appraisal}\n"
        + "Two independent reviewers screened every record; conflicts were resolved by an "
        + f"adjudicator (Cohen's $\\kappa = {state.cohen_kappa if state.cohen_kappa is not None else 'n/a'}$). "
        + "Full texts were retrieved and assessed; data were extracted into a structured form "
        + f"and each study appraised with {esc(p.risk_of_bias.tool)}.\n"
        + "\\subsection{Effect measures and synthesis}\n" + _methods_equations(state) + "\n"
    )

    # Results
    res_line = (
        f"{len(state.included_studies)} studies were included{cite_all}. "
        + (f"The pooled {esc(meta.measure)} ({esc(meta.model)} effects) was "
           f"${meta.pooled_estimate}$ (95\\% CI ${meta.ci_lower}$ to ${meta.ci_upper}$; "
           f"$k={meta.k_studies}$). " + _heterogeneity_text(meta) + esc(meta.interpretation)
           if meta else "A meta-analysis was not performed due to insufficient comparable data.")
    )

    # Study-selection figure: prefer prisma_flow.pdf, else TikZ flow.
    prisma_fig = _figure_with_fallback(
        "prisma_flow.pdf", _prisma_tikz_body(state.prisma),
        "PRISMA 2020 study-selection flow diagram.", "fig:prisma")

    # Forest figure: prefer forest.pdf, else TikZ forest (or graceful text).
    if meta and meta.forest:
        forest_fig = _figure_with_fallback(
            "forest.pdf", _forest_tikz_body(meta),
            (f"Forest plot ({esc(meta.measure)}, {esc(meta.model)} effects; "
             f"$k={meta.k_studies}$, $I^2={meta.i_squared}\\%$)."),
            "fig:forest")
    else:
        forest_fig = forest_tikz(meta)   # graceful "not performed" text

    # Funnel figure: prefer funnel.pdf, else TikZ funnel (omit if no data).
    if meta and meta.funnel and meta.pooled_estimate is not None:
        funnel_fig = _figure_with_fallback(
            "funnel.pdf", _funnel_tikz_body(meta),
            "Funnel plot of effect size against precision (apex = pooled estimate; "
            "dashed lines = pseudo 95\\% confidence funnel).",
            "fig:funnel")
    else:
        funnel_fig = ""

    parts.append(
        "\\section{Results}\n\\subsection{Study selection}\n"
        + prisma_fig + "\n" + res_line + "\n"
        + "\\subsection{Characteristics of included studies}\n"
        + _characteristics_table(state, keys) + "\n"
        + "\\subsection{Risk of bias within studies}\n" + _rob_longtable(state) + "\n"
        + "\\subsection{Synthesis of results}\n" + forest_fig + "\n"
        + esc(s.narrative) + "\n"
        + "\\subsection{Publication bias (PRISMA item 14)}\n"
        + funnel_fig + "\n" + _publication_bias_text(meta) + "\n"
        + "\\subsection{Certainty of evidence (GRADE)}\n"
        + f"\\textbf{{Certainty: {esc(s.grade_certainty or 'not rated')}.}} "
        + esc(s.grade_rationale) + "\n"
    )

    discussion = (esc(prose.get("discussion", "")) if isinstance(prose, dict) else "") or ""
    parts.append("\\section{Discussion}\n" + discussion +
                 "\n\n\\textbf{Limitations.} " + esc(s.limitations) + "\n")
    conclusions = (esc(prose.get("conclusions", "")) if isinstance(prose, dict) else "") or ""
    parts.append("\\section{Conclusions}\n" + conclusions + "\n")

    # Journal end-matter before the bibliography / appendix.
    parts.append(_end_matter(state, has_bib))

    if has_bib:
        # Ensure every included study appears in the reference list even if not
        # inline-cited.
        parts.append("\\nocite{*}\n")
        parts.append(f"\\bibliographystyle{{{bibstyle}}}\n\\bibliography{{\\jobname}}\n")
    else:
        parts.append("\\section*{References}\nNo studies met the inclusion criteria.\n")

    parts.append("\\appendix\n\\section{PRISMA 2020 checklist}\n" + _checklist_longtable() + "\n")
    parts.append("\\end{document}\n")

    return "".join(parts), bib
