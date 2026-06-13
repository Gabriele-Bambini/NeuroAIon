"""LaTeX rendering — turn a completed review into a publication-grade paper.

Produces a single self-contained ``paper.tex`` (compilable with
``latexmk -pdf``) containing: title/abstract, methods with typeset estimator
equations, a TikZ PRISMA 2020 flow diagram, a TikZ forest plot, booktabs tables
(characteristics, risk of bias), the GRADE rating, the 27-item PRISMA checklist,
and an embedded BibTeX bibliography. Figures are pure TikZ (vector, no external
image files), so the document compiles anywhere TeX + TikZ are available.
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
    "θ": r"$\theta$", "χ": r"$\chi$", "°": r"$^{\circ}$", " ": " ",
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


# ── Preamble (static; raw to avoid brace-escaping headaches) ─────────────────
_PREAMBLE = r"""\documentclass[11pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[margin=1in]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{textcomp}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{array}
\usepackage{caption}
\usepackage{float}
\usepackage[hidelinks]{hyperref}
\usepackage{tikz}
\usetikzlibrary{shapes.geometric,arrows.meta,positioning,calc}
\setlength{\parskip}{0.5em}
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
    def f(field: str, value: str) -> str:
        return f"  {field} = {{{value}}},\n" if value else ""
    authors = " and ".join(rec.authors) if rec.authors else "Anonymous"
    body = (
        f"@article{{{key},\n"
        + f("title", rec.title.replace("{", "").replace("}", ""))
        + f("author", authors)
        + f("journal", rec.journal)
        + (f"  year = {{{rec.year}}},\n" if rec.year else "")
        + f("doi", rec.doi)
        + f("url", rec.url)
        + "}\n"
    )
    return body


def _methods_equations(state: ReviewState) -> str:
    """Typeset the actual estimators used, so the methods are fully reproducible."""
    measure = state.protocol.synthesis.effect_measure
    model = state.protocol.synthesis.model
    eqs = [
        r"For each study $i$ the effect estimate $y_i$ was combined by "
        r"inverse-variance weighting, $w_i = 1/\mathrm{SE}_i^2$, giving the "
        r"pooled estimate",
        r"\begin{equation}",
        r"\hat{\theta} = \frac{\sum_i w_i\, y_i}{\sum_i w_i}, \qquad "
        r"\mathrm{SE}(\hat{\theta}) = \sqrt{\tfrac{1}{\sum_i w_i}}.",
        r"\end{equation}",
        r"Heterogeneity was quantified with Cochran's $Q$, the $I^2$ statistic, "
        r"and (for the random-effects model) the DerSimonian--Laird estimator of "
        r"the between-study variance $\tau^2$:",
        r"\begin{equation}",
        r"Q = \sum_i w_i (y_i-\hat{\theta}_{\mathrm{FE}})^2, \quad "
        r"I^2 = \max\!\left(0,\ \frac{Q-(k-1)}{Q}\right)\times 100\%, \quad "
        r"\hat{\tau}^2 = \max\!\left(0,\ \frac{Q-(k-1)}{\sum_i w_i - "
        r"\frac{\sum_i w_i^2}{\sum_i w_i}}\right).",
        r"\end{equation}",
    ]
    if model == "random":
        eqs += [
            r"Under random effects the weights become "
            r"$w_i^{*} = 1/(\mathrm{SE}_i^2 + \hat{\tau}^2)$. ",
        ]
    eqs.append(
        r"Inter-rater agreement at title/abstract screening was summarised with "
        r"Cohen's $\kappa = (p_o - p_e)/(1 - p_e)$, where $p_o$ and $p_e$ are the "
        r"observed and chance-expected agreement."
    )
    eqs.append(
        f"The effect measure was the {esc(measure)} "
        f"({'standardised mean difference' if measure=='SMD' else esc(measure)}); "
        f"ratio measures were pooled on the natural-log scale."
    )
    return "\n".join(eqs)


def prisma_tikz(flow: PrismaFlow) -> str:
    """A PRISMA 2020 flow diagram drawn in pure TikZ (vector, self-contained)."""
    ident = r"\\ ".join(f"{esc(k)}: {v}" for k, v in flow.records_identified.items()) or "--"
    excl_reports = sum(flow.reports_excluded.values())
    box = ("box/.style={draw, rounded corners, align=center, text width=5.2cm, "
           "inner sep=4pt, font=\\small}")
    side = ("side/.style={draw, align=center, text width=4.6cm, inner sep=4pt, "
            "font=\\small}")
    return (
        "\\begin{figure}[H]\n\\centering\n"
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
        "\\caption{PRISMA 2020 study-selection flow diagram.}\n"
        "\\end{figure}\n"
    )


def forest_tikz(meta: Optional[MetaAnalysisResult]) -> str:
    """A forest plot drawn in pure TikZ from the pooled meta-analysis."""
    if not meta or not meta.forest:
        return "\\textit{Meta-analysis not performed (insufficient comparable data).}\n"
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
    L = ["\\begin{figure}[H]\n\\centering\n",
         "\\begin{tikzpicture}[x=1cm,y=1cm,font=\\scriptsize,>=Stealth]\n"]
    # Null reference line + axis.
    L.append(f"\\draw[dashed,gray] ({X(null):.3f},{-0.7:.3f}) -- "
             f"({X(null):.3f},{top + 0.3:.3f});\n")
    L.append(f"\\draw[->] (0,{-0.7:.3f}) -- ({W + 0.2:.3f},{-0.7:.3f});\n")
    for tv in sorted({lo + pad, null, hi - pad}):
        L.append(f"\\draw ({X(tv):.3f},{-0.7:.3f}) -- ({X(tv):.3f},{-0.85:.3f}) "
                 f"node[below] {{{tv:.2f}}};\n")
    # Per-study rows (top to bottom).
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
    # Pooled diamond at y=0.
    pe, pl, pu = meta.pooled_estimate, meta.ci_lower, meta.ci_upper
    L.append(f"\\fill[black!80] ({X(pl):.3f},0) -- ({X(pe):.3f},0.18) -- "
             f"({X(pu):.3f},0) -- ({X(pe):.3f},-0.18) -- cycle;\n")
    L.append(f"\\node[left] at ({-0.25:.3f},0) {{Pooled ({esc(meta.model)})}};\n")
    L.append(f"\\node[right] at ({W + 0.35:.3f},0) "
             f"{{{pe:.2f} [{pl:.2f}, {pu:.2f}]}};\n")
    L.append("\\end{tikzpicture}\n")
    L.append(f"\\caption{{Forest plot ({esc(meta.measure)}, {esc(meta.model)} effects; "
             f"$k={meta.k_studies}$, $I^2={meta.i_squared}\\%$).}}\n")
    L.append("\\end{figure}\n")
    return "".join(L)


def funnel_tikz(meta: Optional[MetaAnalysisResult]) -> str:
    """A funnel plot (effect vs. standard error) with a pseudo-95% CI funnel."""
    if not meta or not meta.funnel or meta.pooled_estimate is None:
        return ""
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
        return H * (1.0 - se / max_se)   # SE=0 at top, max SE at bottom

    L = ["\\begin{figure}[H]\n\\centering\n",
         "\\begin{tikzpicture}[x=1cm,y=1cm,font=\\scriptsize,>=Stealth]\n"]
    # Axes.
    L.append(f"\\draw[->] (0,0) -- ({W + 0.3:.3f},0) node[right] {{{esc(meta.measure)}}};\n")
    L.append(f"\\draw[->] ({X(pooled):.3f},0) -- ({X(pooled):.3f},{H + 0.3:.3f}) "
             f"node[above] {{precision}};\n")
    # Pseudo 95% CI funnel (triangle from pooled apex at SE=0 widening downward).
    apex_x, apex_y = X(pooled), Y(0.0)
    lx, ly = X(pooled - 1.96 * max_se), Y(max_se)
    rx, ry = X(pooled + 1.96 * max_se), Y(max_se)
    L.append(f"\\draw[dashed,gray] ({apex_x:.3f},{apex_y:.3f}) -- ({lx:.3f},{ly:.3f});\n")
    L.append(f"\\draw[dashed,gray] ({apex_x:.3f},{apex_y:.3f}) -- ({rx:.3f},{ry:.3f});\n")
    L.append(f"\\draw[dotted] ({X(pooled):.3f},0) -- ({X(pooled):.3f},{H:.3f});\n")
    # Study points.
    for p in pts:
        L.append(f"\\fill ({X(p['estimate']):.3f},{Y(p['se']):.3f}) circle (1.6pt);\n")
    L.append("\\end{tikzpicture}\n")
    L.append("\\caption{Funnel plot of effect size against precision (apex = pooled "
             "estimate; dashed lines = pseudo 95\\% confidence funnel).}\n\\end{figure}\n")
    return "".join(L)


def _publication_bias_text(meta: Optional[MetaAnalysisResult]) -> str:
    if not meta or meta.eggers_p is None:
        return ("Publication bias was not formally tested (fewer than three studies "
                "with usable variances).")
    asym = "evidence of" if meta.eggers_p < 0.10 else "no strong evidence of"
    power = " Note that with $k<10$ the test is under-powered." \
        if (meta.eggers_k or 0) < 10 else ""
    return (f"Egger's regression test indicated {asym} funnel asymmetry "
            f"(intercept $={meta.eggers_intercept}$, $p={meta.eggers_p}$, "
            f"$k={meta.eggers_k}$).{power}")


def _characteristics_longtable(state: ReviewState, keys: dict[str, str]) -> str:
    rob = {r.uid: r.overall for r in state.rob}
    head = (
        "\\begin{longtable}{p{3.0cm} l c p{3.2cm} c}\n\\toprule\n"
        "Study & Design & $n$ & Population & RoB \\\\\n\\midrule\n\\endhead\n"
    )
    rows = []
    for ex in state.extractions:
        cite = f"\\cite{{{keys[ex.uid]}}}" if ex.uid in keys else ""
        rows.append(
            f"{esc(ex.study_label)}~{cite} & {esc(ex.design or '--')} & "
            f"{ex.sample_size or '--'} & {esc((ex.population or '--')[:60])} & "
            f"{esc(rob.get(ex.uid, '--'))} \\\\\n"
        )
    return head + "".join(rows) + "\\bottomrule\n\\caption{Characteristics of included studies.}\n\\end{longtable}\n"


def _rob_longtable(state: ReviewState) -> str:
    if not state.rob:
        return "\\textit{No included studies were appraised.}\n"
    domains = [d.name for d in state.rob[0].domains]
    colspec = "p{3.2cm} " + " ".join(["c"] * len(domains)) + " c"
    head = ("\\begin{longtable}{" + colspec + "}\n\\toprule\nStudy & "
            + " & ".join(f"\\rotatebox{{0}}{{{esc(d[:14])}}}" for d in domains)
            + " & Overall \\\\\n\\midrule\n\\endhead\n")
    rows = []
    for a in state.rob:
        jud = {d.name: d.judgement for d in a.domains}
        cells = " & ".join(esc(jud.get(d, "--")) for d in domains)
        rows.append(f"{esc(a.study_label[:24])} & {cells} & {esc(a.overall)} \\\\\n")
    return head + "".join(rows) + "\\bottomrule\n\\caption{Risk-of-bias assessment (" \
        + esc(state.rob[0].tool) + ").}\n\\end{longtable}\n"


def _checklist_longtable() -> str:
    from .prisma import CHECKLIST_2020
    cov = PRISMAReporter.coverage_map()
    head = ("\\begin{longtable}{c p{3.2cm} p{6.0cm} p{3.2cm}}\n\\toprule\n"
            "\\# & Item & Description & Addressed by \\\\\n\\midrule\n\\endhead\n")
    rows = []
    for num, name, desc in CHECKLIST_2020:
        rows.append(f"{num} & {esc(name)} & {esc(desc)} & {esc(cov.get(num,'report'))} \\\\\n")
    return head + "".join(rows) + "\\bottomrule\n\\caption{PRISMA 2020 checklist.}\n\\end{longtable}\n"


def build_document(state: ReviewState, prose: dict[str, str]) -> tuple[str, str]:
    """Return (paper_tex, references_bib)."""
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

    abstract = esc(prose.get("abstract", "")) or (
        f"We systematically reviewed the effect of {esc(p.pico.intervention)} on "
        f"{esc(p.pico.outcome)}. {len(state.included_studies)} studies were included."
    )

    cite_all = ""
    if keys:
        cite_all = " \\citep{" + ",".join(keys.values()) + "}"

    has_bib = bool(bib_parts)
    parts: list[str] = [_PREAMBLE]
    parts.append("\\usepackage[numbers,sort&compress]{natbib}\n")
    # Embed the bibliography so the document is fully self-contained.
    if has_bib:
        parts.append("\\begin{filecontents*}[overwrite]{\\jobname.bib}\n" + bib +
                     "\n\\end{filecontents*}\n")
    parts.append(f"\\title{{{esc(p.title)}}}\n")
    parts.append("\\author{NeuroAIon automated systematic review engine"
                 + (f"\\\\ \\small Contact: {esc(p.authors_contact)}" if p.authors_contact else "")
                 + "}\n")
    parts.append("\\date{\\today}\n\\begin{document}\n\\maketitle\n")
    parts.append("\\begin{abstract}\n" + abstract + "\n\\end{abstract}\n")

    parts.append("\\section{Introduction}\n" + (esc(prose.get("background", "")) or
                 esc("This review addresses the question: " + p.question)) + "\n")

    # Methods
    inc = "".join(f"\\item {esc(c)}\n" for c in p.inclusion_criteria) or "\\item ---\n"
    exc = "".join(f"\\item {esc(c)}\n" for c in p.exclusion_criteria) or "\\item ---\n"
    sources = ", ".join(esc(x) for x in (state.prisma.records_identified or p.search.sources))
    parts.append(
        "\\section{Methods}\n"
        + (esc(prose.get("methods", "")) or
           "This review was conducted and reported in accordance with PRISMA 2020.") + "\n\n"
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
    meta = s.meta_analysis
    res_line = (
        f"{len(state.included_studies)} studies were included{cite_all}. "
        + (f"The pooled {esc(meta.measure)} ({esc(meta.model)} effects) was "
           f"${meta.pooled_estimate}$ (95\\% CI ${meta.ci_lower}$ to ${meta.ci_upper}$; "
           f"$I^2={meta.i_squared}\\%$, $k={meta.k_studies}$). " + esc(meta.interpretation)
           if meta else "A meta-analysis was not performed due to insufficient comparable data.")
    )
    parts.append(
        "\\section{Results}\n\\subsection{Study selection}\n"
        + prisma_tikz(state.prisma) + "\n" + res_line + "\n"
        + "\\subsection{Characteristics of included studies}\n"
        + _characteristics_longtable(state, keys) + "\n"
        + "\\subsection{Risk of bias within studies}\n" + _rob_longtable(state) + "\n"
        + "\\subsection{Synthesis of results}\n" + forest_tikz(meta) + "\n"
        + esc(s.narrative) + "\n"
        + "\\subsection{Publication bias (PRISMA item 14)}\n"
        + funnel_tikz(meta) + "\n" + _publication_bias_text(meta) + "\n"
        + "\\subsection{Certainty of evidence (GRADE)}\n"
        + f"\\textbf{{Certainty: {esc(s.grade_certainty or 'not rated')}.}} "
        + esc(s.grade_rationale) + "\n"
    )

    parts.append("\\section{Discussion}\n" + (esc(prose.get("discussion", "")) or "") +
                 "\n\n\\textbf{Limitations.} " + esc(s.limitations) + "\n")
    parts.append("\\section{Conclusions}\n" + (esc(prose.get("conclusions", "")) or "") + "\n")

    parts.append("\\appendix\n\\section{PRISMA 2020 checklist}\n" + _checklist_longtable() + "\n")
    if has_bib:
        parts.append("\\bibliographystyle{unsrtnat}\n\\bibliography{\\jobname}\n")
    else:
        parts.append("\\section*{References}\nNo studies met the inclusion criteria.\n")
    parts.append("\\end{document}\n")

    return "".join(parts), bib
