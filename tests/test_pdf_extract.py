"""Professional PDF content extraction (text, sections, references, statistics).

Builds a real PDF with reportlab, then extracts it with PyMuPDF — fully offline.
"""
import pytest

pytest.importorskip("fitz")        # PyMuPDF (neuroaion[pdf-extract])
pytest.importorskip("reportlab")

from neuroaion.models import Record
from neuroaion.sources import pdf_extract


_LINES = [
    "Anodal tDCS over the DLPFC improves working memory",
    "https://doi.org/10.1234/jcn.2021.0042",
    "Abstract",
    "We tested anodal tDCS in a sham-controlled crossover trial.",
    "Introduction",
    "Working memory is a core component of executive function.",
    "Methods",
    "We enrolled n = 40 healthy adults in a randomized crossover design.",
    "Results",
    "The effect favoured tDCS (SMD = 0.45, 95% CI 0.12 to 0.78, p = 0.003).",
    "Accuracy was 2.1 +/- 0.5 versus 1.6 +/- 0.4 for sham; AUROC 0.82.",
    "Figure 1. Forest plot of standardized mean differences.",
    "Table 1. Characteristics of the included participants.",
    "Discussion",
    "These findings suggest a modest benefit of anodal tDCS.",
    "References",
    "[1] Rossi A, Bianchi L. tDCS and memory. J Cogn Neurosci. 2021.",
    "[2] Neri B. Executive function review. Brain. 2020.",
]


def _make_pdf(path, lines=_LINES):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    c = canvas.Canvas(str(path), pagesize=A4)
    # "±" is drawn as "+/-" above so the text layer is ASCII-clean for the regex
    # (the harvester also matches the real ± glyph).
    y = 800
    for ln in lines:
        c.drawString(60, y, ln.replace("+/-", "±"))
        y -= 24
        if y < 60:
            c.showPage()
            y = 800
    c.showPage()
    c.save()
    return path


def test_extract_pdf_full_structure(tmp_path):
    pdf = _make_pdf(tmp_path / "rossi2021.pdf")
    doc = pdf_extract.extract_pdf(pdf)
    assert doc is not None and doc.backend == "pymupdf"
    assert doc.doi == "10.1234/jcn.2021.0042"
    assert doc.n_pages >= 1
    # IMRaD sections segmented.
    for sec in ("introduction", "methods", "results", "references"):
        assert sec in doc.sections, f"missing section {sec}"
    assert "working memory" in doc.full_text.lower()


def test_statistics_harvested(tmp_path):
    pdf = _make_pdf(tmp_path / "stats.pdf")
    doc = pdf_extract.extract_pdf(pdf)
    blob = "\n".join(doc.statistics).lower()
    assert "p_value" in blob and "p" in blob          # p = 0.003
    assert "ci" in blob                               # 95% CI 0.12 to 0.78
    assert "n" in blob                                # n = 40
    assert "effect" in blob                           # SMD = 0.45
    assert "mean_sd" in blob                          # 2.1 ± 0.5


def test_captions_and_references(tmp_path):
    pdf = _make_pdf(tmp_path / "refs.pdf")
    doc = pdf_extract.extract_pdf(pdf)
    caps = " ".join(doc.captions)
    assert "Figure 1" in caps and "Table 1" in caps
    assert len(doc.references) >= 2


def test_working_text_appends_digest(tmp_path):
    pdf = _make_pdf(tmp_path / "wt.pdf")
    doc = pdf_extract.extract_pdf(pdf)
    wt = doc.as_working_text()
    assert "REPORTED STATISTICS" in wt and "REFERENCES" in wt
    assert "working memory" in wt.lower()


def test_extract_text_from_bytes(tmp_path):
    pdf = _make_pdf(tmp_path / "bytes.pdf")
    raw = (tmp_path / "bytes.pdf").read_bytes()
    text = pdf_extract.extract_text_from_bytes(raw)
    assert "DLPFC" in text and "Methods" in text


def test_match_and_local_retriever(tmp_path):
    folder = tmp_path / "pdfs"
    folder.mkdir()
    _make_pdf(folder / "rossi2021.pdf")
    rec = Record(source="pubmed", source_id="1", doi="10.1234/jcn.2021.0042",
                 title="Anodal tDCS over the DLPFC improves working memory")
    # Matching by DOI.
    docs = pdf_extract.extract_dir(folder)
    assert len(docs) == 1
    matched = pdf_extract.match_documents(docs, [rec])
    assert rec.uid in matched

    retr = pdf_extract.LocalPdfFullTextRetriever(folder)
    assert retr.index([rec]) == 1
    ft = retr.retrieve(rec)
    assert ft.retrieved and ft.source == "local-pdf"
    assert "working memory" in ft.text.lower()
    assert "REPORTED STATISTICS" in ft.text


def test_local_retriever_falls_back(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    rec = Record(source="pubmed", source_id="2", doi="10.9/none",
                 title="Unmatched", abstract="Only an abstract here.")
    retr = pdf_extract.LocalPdfFullTextRetriever(folder)
    retr.index([rec])
    ft = retr.retrieve(rec)
    assert ft.source == "abstract" and "abstract" in ft.text.lower()
