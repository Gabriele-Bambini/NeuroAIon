"""Compile the Markdown dossier (risk-of-bias worksheets etc.) into PDFs."""
import pytest

pytest.importorskip("reportlab")

from neuroaion import docs_pdf


def test_render_markdown_tables_and_inline():
    md = (
        "# Title\n\n"
        "Some **bold** and _italic_ and `code` text.\n\n"
        "## Domain 1 — **Low**\n\n"
        "| Signalling question | Answer |\n"
        "|---|---|\n"
        "| 1.1 Random sequence | Yes |\n"
        "| 1.2 Concealed | No information |\n\n"
        "- bullet one\n- bullet two\n"
    )
    flow = docs_pdf.render_markdown(md)
    assert len(flow) >= 4                       # heading, paragraph, table, list
    # The table flowable is present.
    from reportlab.platypus import Table
    assert any(isinstance(f, Table) for f in flow)


def test_compile_dossier(tmp_path):
    from neuroaion import documents
    from neuroaion.models import (EffectEstimate, ExtractionRecord, PrismaFlow,
                                  Record, ReviewProtocol, ReviewState, RoBAssessment,
                                  RoBDomain, Synthesis, MetaAnalysisResult, GradeRow)
    r = Record(source="pubmed", source_id="1", doi="10.1/x", title="A trial",
               authors=["Rossi A"], year=2021)
    st = ReviewState(run_id="t", protocol=ReviewProtocol(title="T", question="Q?"))
    st.unique_records = [r]
    st.included_studies = [r.uid]
    st.extractions = [ExtractionRecord(uid=r.uid, study_label="Rossi 2021", design="RCT",
                                       sample_size=40, effects=[EffectEstimate(estimate=0.4, se=0.2)])]
    st.rob = [RoBAssessment(uid=r.uid, study_label="Rossi 2021", tool="RoB2",
                            domains=[RoBDomain(name="Randomization process", judgement="low",
                                               support_for_judgement="Computer-generated.",
                                               signalling_answers={"1.1 Random": "Yes"})],
                            overall="some concerns", rationale="ok")]
    st.synthesis = Synthesis(narrative="n", grade_certainty="low",
                             grade_table=[GradeRow(outcome="ADR", n_studies=1, certainty="low",
                                                   risk_of_bias="serious", effect="RR 1.2")],
                             meta_analysis=MetaAnalysisResult(measure="RR", k_studies=1,
                                                              pooled_estimate=1.2))
    st.prisma = PrismaFlow(records_total=2, records_screened=2, studies_included=1)

    documents.write_documents(tmp_path, st)
    written = docs_pdf.compile_dossier(tmp_path, st)
    assert "risk_of_bias" in written
    rob_pdf = (tmp_path / "documents" / "risk_of_bias.pdf")
    assert rob_pdf.exists()
    data = rob_pdf.read_bytes()
    assert data[:5] == b"%PDF-" and len(data) > 1000
    assert (tmp_path / "documents" / "supplementary_materials.pdf").exists()
