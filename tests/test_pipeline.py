"""End-to-end smoke test of the full-auto pipeline in offline mock mode."""
from pathlib import Path

from neuroaion.models import Record
from neuroaion.orchestrator import Orchestrator
from neuroaion.sources import FullText

SEED = {
    "title": "tDCS and working memory: a test review",
    "pico": {
        "population": "Healthy adults",
        "intervention": "Anodal tDCS over DLPFC",
        "comparator": "Sham",
        "outcome": "Working-memory performance",
        "study_designs": ["randomized controlled trial"],
    },
    "question": "auto",
    "inclusion_criteria": ["Human RCTs", "Reports a working-memory outcome"],
    "exclusion_criteria": ["Animal studies", "Reviews"],
    "search": {"sources": ["pubmed", "europepmc", "openalex"],
               "max_records_per_source": 20,
               "keywords": [["tDCS"], ["working memory"]]},
    "synthesis": {"effect_measure": "SMD", "model": "random", "min_studies_for_meta": 2},
    "risk_of_bias": {"tool": "RoB2", "grade": True},
}


def test_full_pipeline_mock(tmp_path: Path):
    orch = Orchestrator(SEED, mock=True, live_sources=False, max_workers=4)
    assert orch.mock is True
    state = orch.run(out_root=tmp_path)

    # Artefacts exist.
    run_dir = tmp_path / state.run_id
    for fname in ("report.md", "state.json", "prisma_flow.json",
                  "included_studies.csv", "extractions.json"):
        assert (run_dir / fname).exists(), f"missing {fname}"

    # PRISMA flow is internally consistent.
    f = state.prisma
    assert f.records_total >= f.records_screened          # duplicates removed
    assert f.records_screened == len(state.unique_records)
    assert f.studies_included == len(state.included_studies)
    assert f.studies_included <= f.reports_assessed + f.reports_not_retrieved

    # The pipeline produced a usable report.
    report = (run_dir / "report.md").read_text()
    assert "PRISMA 2020 checklist" in report
    assert "flowchart" in report  # mermaid flow diagram embedded


class _FakeRetriever:
    """An injectable retriever that returns 'full text' for every record — proves
    the retrieval phase is wired into eligibility/extraction/risk-of-bias."""
    def __init__(self):
        self.calls = 0

    def retrieve(self, record: Record) -> FullText:
        self.calls += 1
        return FullText(text=f"FULL TEXT BODY for {record.title}. " * 20,
                        retrieved=True, source="pmc", pmcid="PMC999")


def test_injected_fulltext_retriever_is_used(tmp_path: Path):
    retr = _FakeRetriever()
    orch = Orchestrator(SEED, mock=True, live_sources=False, max_workers=4,
                        fulltext_retriever=retr)
    state = orch.run(out_root=tmp_path)

    # The retriever was invoked once per record sought for retrieval.
    assert retr.calls == len(state.included_after_screening) > 0
    # Eligibility decisions record that a full text (PMC) was retrieved.
    assert all(e.full_text_retrieved for e in state.eligibility)
    assert any("source: pmc/PMC999" in e.notes for e in state.eligibility)
    # With full text retrieved for every report, none are 'not retrieved'.
    assert state.prisma.reports_not_retrieved == 0


def test_screen_then_resume_handoff(tmp_path: Path):
    """Split run: stop after screening (cheap model) → export → resume (redaction)."""
    # Phase 1 — screening only, with a handoff export.
    o1 = Orchestrator(SEED, mock=True, live_sources=False, max_workers=4,
                      stop_after="screen")
    s1 = o1.run(out_root=tmp_path)
    run_dir = tmp_path / s1.run_id
    assert (run_dir / "screening_handoff.json").exists()
    assert not (run_dir / "report.md").exists()      # redaction not done yet
    assert s1.included_after_screening and not s1.included_studies

    # Phase 2 — resume the redaction half from the checkpoint.
    o2 = Orchestrator(SEED, mock=True, live_sources=False, max_workers=4,
                      from_state=s1)
    s2 = o2.run(out_root=tmp_path)
    write_dir = tmp_path / (s1.run_id + "-writeup")
    assert (write_dir / "report.md").exists()
    assert (write_dir / "paper.tex").exists()
    assert s2.prisma.studies_included == len(s2.included_studies)


def test_determinism_mock(tmp_path: Path):
    """Mock runs are deterministic given identical input → same selection counts."""
    s1 = Orchestrator(SEED, mock=True, live_sources=False, max_workers=2).run(tmp_path / "a")
    s2 = Orchestrator(SEED, mock=True, live_sources=False, max_workers=2).run(tmp_path / "b")
    assert s1.prisma.records_screened == s2.prisma.records_screened
    assert len(s1.included_after_screening) == len(s2.included_after_screening)
