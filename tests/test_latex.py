"""LaTeX rendering: escaping, structural validity, figures, and bibliography."""
import re

from neuroaion.latex import build_document, esc, forest_tikz, prisma_tikz
from neuroaion.models import (EffectEstimate, ExtractionRecord, MetaAnalysisResult,
                              PrismaFlow, Record, ReviewProtocol, ReviewState,
                              RoBAssessment, RoBDomain, Synthesis)


def _demo_state() -> ReviewState:
    rec = Record(source="pubmed", source_id="1", doi="10.1/x",
                 title="tDCS & memory: a 50% better study #1",
                 authors=["Rossi A", "Bianchi L"], year=2021, journal="NeuroImage")
    st = ReviewState(run_id="t", model="mock",
                     protocol=ReviewProtocol(title="A test review of tDCS_effects",
                                             question="Does tDCS help?",
                                             inclusion_criteria=["RCTs"],
                                             exclusion_criteria=["Animals"]))
    st.unique_records = [rec]
    st.included_studies = [rec.uid]
    st.extractions = [ExtractionRecord(uid=rec.uid, study_label="Rossi 2021",
                                       design="RCT", sample_size=40,
                                       population="Healthy adults",
                                       effects=[EffectEstimate(estimate=0.4, se=0.2)])]
    st.rob = [RoBAssessment(uid=rec.uid, study_label="Rossi 2021", tool="RoB2",
                            domains=[RoBDomain(name="Randomization", judgement="low")],
                            overall="low")]
    st.synthesis = Synthesis(
        narrative="The effect was positive but uncertain.",
        grade_certainty="low", grade_rationale="Imprecision & risk of bias.",
        meta_analysis=MetaAnalysisResult(
            measure="SMD", model="random", k_studies=2, pooled_estimate=0.35,
            ci_lower=0.05, ci_upper=0.65, i_squared=10.0,
            forest=[{"study": "Rossi 2021", "estimate": 0.4, "ci_lower": 0.0,
                     "ci_upper": 0.8, "weight_pct": 60.0},
                    {"study": "Smith 2022", "estimate": 0.3, "ci_lower": -0.1,
                     "ci_upper": 0.7, "weight_pct": 40.0}],
            interpretation="Heterogeneity was low."))
    st.prisma = PrismaFlow(records_identified={"pubmed": 100}, records_total=100,
                           duplicates_removed=20, records_screened=80,
                           records_excluded_screening=60, reports_sought=20,
                           reports_not_retrieved=2, reports_assessed=18,
                           reports_excluded={"Wrong population": 17}, studies_included=1)
    return st


def test_escape_special_chars():
    out = esc("50% gain & cost_$ {x} #1")
    for bad in ["%", "&", "_", "$", "#"]:
        # every special char must be backslash-escaped (preceded by a backslash)
        assert re.search(rf"(?<!\\)\\{re.escape(bad)}", out) or bad not in out


def _balanced_environments(tex: str) -> bool:
    begins = re.findall(r"\\begin\{(\w+\*?)\}", tex)
    ends = re.findall(r"\\end\{(\w+\*?)\}", tex)
    from collections import Counter
    return Counter(begins) == Counter(ends)


def _balanced_braces(tex: str) -> bool:
    """Grouping braces must balance once escaped \\{ \\} (and \\% etc.) are removed."""
    stripped = re.sub(r"\\[{}%&$#_]", "", tex)
    depth = 0
    for ch in stripped:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def test_document_is_structurally_valid():
    tex, bib = build_document(_demo_state(), {})
    assert tex.startswith("\\documentclass")
    assert "\\begin{document}" in tex and "\\end{document}" in tex
    assert _balanced_environments(tex), "unbalanced \\begin/\\end environments"
    assert _balanced_braces(tex), "unbalanced grouping braces"
    # Core sections present.
    for sec in ["Introduction", "Methods", "Results", "Discussion", "Conclusions"]:
        assert f"\\section{{{sec}}}" in tex
    # Figures and equations.
    assert "tikzpicture" in tex                      # PRISMA + forest figures
    assert "DerSimonian" in tex or "tau^2" in tex     # estimator equations
    assert "PRISMA 2020 checklist" in tex
    # Bibliography embedded and cited.
    assert "filecontents" in tex and "@article" in bib
    assert "\\citep{" in tex or "\\cite{" in tex


def test_prisma_and_forest_render():
    st = _demo_state()
    assert "Studies included in review" in prisma_tikz(st.prisma)
    forest = forest_tikz(st.synthesis.meta_analysis)
    assert "Pooled" in forest and "tikzpicture" in forest
    # Forest with no data degrades gracefully.
    assert "not performed" in forest_tikz(None)


def test_unicode_is_normalised_for_pdflatex():
    # Characters that break plain pdflatex must be converted, not passed through.
    s = esc("I² rose by 5×; κ=0.8 ± 0.1 — “quoted” … β")
    for raw in ["²", "×", "κ", "±", "—", "“", "”", "…", "β"]:
        assert raw not in s, f"unconverted Unicode {raw!r}"
    assert "\\textsuperscript{2}" in s and "\\kappa" in s


def test_full_document_has_no_raw_unicode_specials():
    tex, _ = build_document(_demo_state(), {
        "abstract": "Heterogeneity I² was 0%, effect ×2, κ high — done.",
        "discussion": "α and β differed ≥ 0.5.",
    })
    for raw in ["²", "×", "κ", "≥", "α", "β", "—"]:
        assert raw not in tex, f"raw Unicode {raw!r} leaked into the document"


def test_no_unescaped_user_specials_in_body():
    tex, _ = build_document(_demo_state(), {})
    # The raw title contained '_' and '%' and '&'; none should appear unescaped
    # inside the \title argument.
    title = re.search(r"\\title\{(.+?)\}", tex).group(1)
    assert "_" not in title.replace("\\_", "")
