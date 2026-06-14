"""Free connectors registry, PROSPERO export, and funnel rendering."""
from neuroaion.models import (MetaAnalysisResult, ReviewProtocol, ReviewState)
from neuroaion.sources import synthetic_records
from neuroaion.sources.registry import SOURCES


def test_all_free_sources_registered():
    for name in ["pubmed", "europepmc", "crossref", "openalex", "biorxiv",
                 "clinicaltrials", "doaj", "semanticscholar", "arxiv"]:
        assert name in SOURCES, f"{name} not registered"
        # Synthetic generation works for every source name (offline/mock path).
        recs = synthetic_records(name, "tDCS working memory", n=3)
        assert len(recs) == 3 and all(r.source == name for r in recs)


def test_prospero_registration_export():
    from neuroaion import prospero
    st = ReviewState(run_id="t", protocol=ReviewProtocol(
        title="tDCS & working memory", question="Does tDCS help WM?",
        inclusion_criteria=["RCTs"], exclusion_criteria=["Animals"],
        authors_contact="x@y.z"))
    md = prospero.build_registration(st)
    assert "PROSPERO registration" in md
    assert "Review question" in md and "Does tDCS help WM?" in md
    assert "Egger's test" in md  # synthesis strategy documented


def test_html_report_self_contained():
    from neuroaion.html_report import build_html
    from neuroaion.models import (PrismaFlow, ReviewProtocol, ReviewState,
                                  Synthesis)
    st = ReviewState(run_id="t", mock=True, model="demo",
                     protocol=ReviewProtocol(title="T", question="Q?"),
                     synthesis=Synthesis(narrative="n", grade_certainty="low",
                                         meta_analysis=MetaAnalysisResult(
                                             measure="SMD", model="random", k_studies=2,
                                             pooled_estimate=0.3, ci_lower=0.1, ci_upper=0.5,
                                             funnel=[{"estimate": 0.3, "se": 0.1}],
                                             forest=[{"study": "A", "estimate": 0.3,
                                                      "ci_lower": 0.0, "ci_upper": 0.6,
                                                      "weight_pct": 100.0}])),
                     prisma=PrismaFlow(records_total=10, records_screened=8,
                                       studies_included=2))
    html = build_html(st, {"abstract": "A & B <test>"})
    assert html.startswith("<!doctype html>")
    assert "<svg" in html                      # inline figures, no external deps
    assert "Studies included" in html
    assert "&amp;" in html and "&lt;test&gt;" in html  # user text escaped


def test_funnel_tikz_renders_and_degrades():
    from neuroaion.latex import funnel_tikz
    meta = MetaAnalysisResult(measure="SMD", model="random", k_studies=3,
                              pooled_estimate=0.3, ci_lower=0.0, ci_upper=0.6,
                              eggers_intercept=0.5, eggers_p=0.2, eggers_k=3,
                              funnel=[{"estimate": 0.2, "se": 0.1},
                                      {"estimate": 0.4, "se": 0.3}])
    out = funnel_tikz(meta)
    assert "tikzpicture" in out and "Funnel plot" in out
    assert funnel_tikz(None) == ""             # graceful with no data


def test_pdf_report_generates(tmp_path):
    import pytest
    pytest.importorskip("reportlab")
    from neuroaion.pdf_report import build_pdf
    from neuroaion.models import (MetaAnalysisResult, PrismaFlow, ReviewProtocol,
                                  ReviewState, Synthesis)
    st = ReviewState(run_id="t", protocol=ReviewProtocol(title="T", question="Q?"),
                     synthesis=Synthesis(narrative="n", grade_certainty="low",
                                         meta_analysis=MetaAnalysisResult(
                                             measure="SMD", model="random", k_studies=2,
                                             pooled_estimate=0.3, ci_lower=0.1, ci_upper=0.5,
                                             funnel=[{"estimate": 0.3, "se": 0.1}],
                                             forest=[{"study": "A", "estimate": 0.3,
                                                      "ci_lower": 0.0, "ci_upper": 0.6,
                                                      "weight_pct": 100.0}])),
                     prisma=PrismaFlow(records_total=10, records_screened=8, studies_included=2))
    out = build_pdf(st, {"abstract": "x"}, tmp_path / "paper.pdf")
    data = out.read_bytes()
    assert data[:5] == b"%PDF-"          # a real PDF
    assert len(data) > 1000


def test_arxiv_parser_offline(monkeypatch):
    """The arXiv Atom parser builds Records (verified without network)."""
    from neuroaion.sources import arxiv
    feed = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <id>http://arxiv.org/abs/2401.01234v1</id>
        <title>Sheaf Neural Networks for Gene Regulatory Network Inference</title>
        <summary>We apply sheaf diffusion to GRN inference and benchmark on BEELINE.</summary>
        <published>2024-01-03T00:00:00Z</published>
        <author><name>Jane Doe</name></author>
        <author><name>John Roe</name></author>
        <arxiv:doi xmlns:arxiv="http://arxiv.org/schemas/atom">10.1234/x</arxiv:doi>
      </entry>
    </feed>"""

    class _Resp:
        text = feed

    monkeypatch.setattr(arxiv, "http_get", lambda *a, **k: _Resp())
    recs = arxiv.search("sheaf gene regulatory network", retmax=5)
    assert len(recs) == 1
    r = recs[0]
    assert r.source == "arxiv" and "Sheaf Neural Networks" in r.title
    assert r.authors == ["Jane Doe", "John Roe"] and r.year == 2024
    assert r.source_id == "2401.01234v1"


def test_arxiv_in_default_sources():
    from neuroaion import frameworks, wizard
    assert "arxiv" in frameworks.DEFAULT_SOURCES
    seed = wizard.build_seed(topic="t", framework="PICO")
    assert "arxiv" in seed["search"]["sources"]
