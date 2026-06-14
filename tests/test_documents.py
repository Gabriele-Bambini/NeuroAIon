"""Formal document dossier + auditable process evidence."""
import json

from neuroaion import audit, documents
from neuroaion.models import (Decision, EffectEstimate, EligibilityDecision,
                              ExtractionRecord, PrismaFlow, Record, ReviewProtocol,
                              ReviewState, RoBAssessment, RoBDomain, ScreeningDecision,
                              Synthesis, MetaAnalysisResult)


def _state() -> ReviewState:
    r = Record(source="pubmed", source_id="1", doi="10.1/x", title="A tDCS trial",
               authors=["Rossi A"], year=2021)
    ex = Record(source="pubmed", source_id="2", doi="10.1/y", title="Excluded one",
                authors=["Neri B"], year=2019)
    st = ReviewState(run_id="t", model="demo", mock=True,
                     protocol=ReviewProtocol(title="T", question="Q?",
                                             inclusion_criteria=["RCT"],
                                             exclusion_criteria=["Animals"]))
    st.unique_records = [r, ex]
    st.included_after_screening = [r.uid]
    st.screening = [
        ScreeningDecision(uid=r.uid, reviewer="reviewer_1", decision=Decision.INCLUDE,
                          reason="on topic"),
        ScreeningDecision(uid=r.uid, reviewer="reviewer_2", decision=Decision.INCLUDE),
        ScreeningDecision(uid=ex.uid, reviewer="reviewer_1", decision=Decision.EXCLUDE,
                          reason="off topic"),
        ScreeningDecision(uid=ex.uid, reviewer="reviewer_2", decision=Decision.EXCLUDE),
    ]
    st.cohen_kappa = 0.8
    st.eligibility = [
        EligibilityDecision(uid=r.uid, eligible=True, full_text_retrieved=True),
        EligibilityDecision(uid=ex.uid, eligible=False, full_text_retrieved=True,
                            exclusion_reason="Wrong comparator"),
    ]
    st.included_studies = [r.uid]
    st.extractions = [ExtractionRecord(uid=r.uid, study_label="Rossi 2021", design="RCT",
                                       sample_size=40,
                                       effects=[EffectEstimate(estimate=0.4, se=0.2)])]
    st.rob = [RoBAssessment(uid=r.uid, study_label="Rossi 2021", tool="RoB2",
                            domains=[RoBDomain(name="Randomization process", judgement="low",
                                               rationale="adequate")],
                            overall="low", rationale="ok")]
    st.synthesis = Synthesis(narrative="n", grade_certainty="low",
                             meta_analysis=MetaAnalysisResult(measure="SMD", model="random",
                                                              k_studies=1, pooled_estimate=0.4,
                                                              ci_lower=0.0, ci_upper=0.8,
                                                              i_squared=0.0))
    st.prisma = PrismaFlow(records_identified={"pubmed": 2}, records_total=2,
                           records_screened=2, reports_assessed=2,
                           reports_excluded={"Wrong comparator": 1}, studies_included=1)
    return st


def test_document_dossier_written(tmp_path):
    st = _state()
    written = documents.write_documents(tmp_path, st)
    names = {p.name for p in written}
    for expected in ["01_protocol.md", "02_search_log.csv", "03_screening_log.csv",
                     "04_excluded_full_text.md", "05_data_extraction_form.csv",
                     "06_risk_of_bias.md", "07_summary_of_findings.md",
                     "08_prisma_checklist.md"]:
        assert expected in names
    # The excluded full-text reason is documented (PRISMA 16b).
    assert "Wrong comparator" in (tmp_path / "documents" / "04_excluded_full_text.md").read_text()
    # Screening log records both reviewers.
    sl = (tmp_path / "documents" / "03_screening_log.csv").read_text()
    assert "reviewer_1" in sl and "reviewer_2" in sl
    # GRADE SoF carries the certainty.
    assert "low" in (tmp_path / "documents" / "07_summary_of_findings.md").read_text()


def test_audit_trail_and_manifest(tmp_path):
    st = _state()
    audit.write_audit(tmp_path, st)
    events = [json.loads(l) for l in
              (tmp_path / "audit_trail.jsonl").read_text().splitlines()]
    phases = {e["phase"] for e in events}
    assert {"screening", "eligibility", "extraction", "risk_of_bias"} <= phases
    assert all("seq" in e and "actor" in e for e in events)
    assert "audit_log.csv" in {p.name for p in tmp_path.iterdir()}

    # Manifest hashes every file and records provenance.
    documents.write_documents(tmp_path, st)
    m = audit.write_manifest(tmp_path, st)
    data = json.loads(m.read_text())
    assert data["engine"] == "NeuroAIon"
    assert data["integrity"]["algorithm"] == "sha256"
    assert data["integrity"]["files"]                      # non-empty checksum set
    assert "manifest.json" not in data["integrity"]["files"]
    assert data["counts"]["studies_included"] == 1
    # Every checksum is a 64-hex SHA-256.
    assert all(len(h) == 64 for h in data["integrity"]["files"].values())
