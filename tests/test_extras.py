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
