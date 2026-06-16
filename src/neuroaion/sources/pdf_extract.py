"""Professional PDF content extraction — pull *everything* out of a report PDF.

Given a scholarly PDF (one the reviewer downloaded through their own legitimate
access, or a legal open-access copy fetched by the pipeline), this extracts a
structured representation: clean reading-order full text, the embedded metadata
and DOI, an IMRaD section map, the tables, the reference list, figure/table
captions, and a harvest of the reported statistics (p-values, confidence
intervals, sample sizes, effect sizes, means ± SD, AUROC/AUPRC). Downstream the
LocalPdfFullTextRetriever hands this to screening, data-extraction and
risk-of-bias as the working full text — so the appraisal is based on the whole
report, not just the abstract.

Backends (best available, all local — NO publisher scraping):
  * PyMuPDF (``fitz``) — fast layout-aware text + table detection. Default.
  * GROBID — if a GROBID server is configured (``GROBID_URL`` env), its
    machine-learning TEI parse is used for header/sections/references.

Optional dependency: ``pip install neuroaion[pdf-extract]`` (pymupdf).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..models import Record
from .fulltext import FullText, FullTextRetriever

_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)

# Canonical IMRaD-ish section headings (order-independent; matched case-folded).
_SECTION_HEADINGS = [
    "abstract", "background", "introduction", "related work", "materials and methods",
    "methods", "materials", "patients and methods", "study design", "data and methods",
    "statistical analysis", "results", "findings", "discussion", "limitations",
    "conclusion", "conclusions", "references", "bibliography", "acknowledgements",
    "supplementary", "appendix",
]
_HEADING_RE = re.compile(
    r"^\s*(?:\d+\.?\d*\s+)?(" + "|".join(re.escape(h) for h in _SECTION_HEADINGS) + r")\s*:?\s*$",
    re.I,
)

# Reported-statistics harvest.
_STAT_PATTERNS = {
    "p_value": re.compile(r"\bp\s*[<>=≤≥]\s*0?\.\d+", re.I),
    "ci": re.compile(r"95\s*%?\s*CI[:\s]*[\[(]?\s*-?\d+\.?\d*\s*(?:,|to|–|-)\s*-?\d+\.?\d*[\])]?", re.I),
    "n": re.compile(r"\bn\s*=\s*\d{1,6}\b", re.I),
    "effect": re.compile(r"\b(?:OR|RR|HR|SMD|MD|aOR|aHR|Cohen'?s?\s*d|Hedges'?\s*g)\s*[=:]\s*-?\d+\.?\d*", re.I),
    "mean_sd": re.compile(r"-?\d+\.?\d*\s*±\s*\d+\.?\d*"),
    "metric": re.compile(r"\b(?:AUROC|AUPRC|AUC|F1|accuracy|sensitivity|specificity|precision|recall)\b[^.\n]{0,18}?\d\.\d+", re.I),
}
_CAPTION_RE = re.compile(r"^\s*((?:Figure|Fig\.?|Table|Supplementary\s+(?:Figure|Table))\s*\d+[.:]?)\s*(.+)$", re.I)


@dataclass
class PdfDocument:
    path: str = ""
    n_pages: int = 0
    title: str = ""
    authors: list[str] = field(default_factory=list)
    doi: str = ""
    abstract: str = ""
    full_text: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    tables: list[list[list[str]]] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    captions: list[str] = field(default_factory=list)
    statistics: list[str] = field(default_factory=list)
    backend: str = ""

    def as_working_text(self, max_chars: int = 60000) -> str:
        """Full text plus an appended structured digest (tables, captions, stats,
        references) so an LLM reader sees *everything* the report contains."""
        parts = [self.full_text.strip()]
        if self.tables:
            parts.append("\n\n=== EXTRACTED TABLES ===")
            for i, tbl in enumerate(self.tables, 1):
                parts.append(f"\n[Table {i}]")
                for row in tbl[:40]:
                    parts.append(" | ".join((c or "").strip() for c in row))
        if self.captions:
            parts.append("\n\n=== FIGURE/TABLE CAPTIONS ===\n" + "\n".join(self.captions))
        if self.statistics:
            parts.append("\n\n=== REPORTED STATISTICS (auto-harvested) ===\n"
                         + "\n".join(self.statistics))
        if self.references:
            parts.append("\n\n=== REFERENCES ===\n"
                         + "\n".join(f"[{i}] {r}" for i, r in enumerate(self.references[:120], 1)))
        return "\n".join(parts).strip()[:max_chars]


# ── harvesting helpers ───────────────────────────────────────────────────────
def harvest_statistics(text: str, *, limit: int = 200) -> list[str]:
    """Return unique reported-statistic snippets with a little surrounding context."""
    found: list[str] = []
    seen: set[str] = set()
    for label, pat in _STAT_PATTERNS.items():
        for m in pat.finditer(text):
            s, e = max(0, m.start() - 30), min(len(text), m.end() + 10)
            ctx = re.sub(r"\s+", " ", text[s:e]).strip()
            key = m.group(0).lower().replace(" ", "")
            if key not in seen:
                seen.add(key)
                found.append(f"[{label}] …{ctx}…")
            if len(found) >= limit:
                return found
    return found


def _segment_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = "_preamble"
    buf: list[str] = []
    for line in text.splitlines():
        m = _HEADING_RE.match(line.strip())
        if m and len(line.strip()) < 60:
            sections[current] = "\n".join(buf).strip()
            current = m.group(1).lower()
            buf = []
        else:
            buf.append(line)
    sections[current] = "\n".join(buf).strip()
    return {k: v for k, v in sections.items() if v}


def _captions(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        m = _CAPTION_RE.match(line.strip())
        if m:
            out.append(f"{m.group(1)} {m.group(2).strip()}"[:300])
    return out[:60]


def _references_from_sections(sections: dict[str, str]) -> list[str]:
    raw = sections.get("references") or sections.get("bibliography") or ""
    if not raw:
        return []
    # Split on numbered markers "[12]" / "12." at line start, else by blank lines.
    items = re.split(r"\n(?=\[\d+\]|\d{1,3}\.\s)", raw)
    refs = [re.sub(r"\s+", " ", it).strip(" .[]") for it in items if len(it.strip()) > 12]
    return refs[:200]


# ── PyMuPDF backend ──────────────────────────────────────────────────────────
def _extract_fitz(path: Path, max_chars: int) -> Optional[PdfDocument]:
    try:
        import fitz  # PyMuPDF
    except Exception:  # noqa: BLE001 — optional dependency
        return None
    try:
        doc = fitz.open(str(path))
    except Exception:  # noqa: BLE001
        return None

    pages_text: list[str] = []
    tables: list[list[list[str]]] = []
    for page in doc:
        try:
            pages_text.append(page.get_text("text"))
        except Exception:  # noqa: BLE001
            pages_text.append("")
        # Table detection (PyMuPDF ≥ 1.23).
        try:
            finder = page.find_tables()
            for tbl in getattr(finder, "tables", []):
                rows = tbl.extract()
                if rows and len(rows) > 1:
                    tables.append([[(c or "") for c in row] for row in rows])
        except Exception:  # noqa: BLE001
            pass

    full_text = re.sub(r"\n{3,}", "\n\n", "\n".join(pages_text)).strip()
    meta = doc.metadata or {}
    sections = _segment_sections(full_text)
    doi_match = _DOI_RE.search(full_text)
    n_pages = doc.page_count
    doc.close()

    return PdfDocument(
        path=str(path), n_pages=n_pages,
        title=(meta.get("title") or "").strip(),
        authors=[a.strip() for a in re.split(r";|,| and ", meta.get("author", "") or "") if a.strip()],
        doi=(doi_match.group(0).rstrip(".") if doi_match else ""),
        abstract=sections.get("abstract", "")[:5000],
        full_text=full_text[:max_chars],
        sections=sections,
        tables=tables,
        references=_references_from_sections(sections),
        captions=_captions(full_text),
        statistics=harvest_statistics(full_text),
        backend="pymupdf",
    )


# ── GROBID backend (optional, ML-grade structured parse) ─────────────────────
def _extract_grobid(path: Path, server_url: str, max_chars: int) -> Optional[PdfDocument]:
    import xml.etree.ElementTree as ET

    import requests
    url = server_url.rstrip("/") + "/api/processFulltextDocument"
    try:
        with open(path, "rb") as fh:
            resp = requests.post(url, files={"input": fh},
                                 data={"consolidateHeader": "1"}, timeout=120)
        resp.raise_for_status()
        tei = resp.text
    except Exception:  # noqa: BLE001
        return None
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    try:
        root = ET.fromstring(tei)
    except ET.ParseError:
        return None

    def txt(node) -> str:
        return re.sub(r"\s+", " ", "".join(node.itertext())).strip() if node is not None else ""

    title = txt(root.find(".//t:titleStmt/t:title", ns))
    abstract = txt(root.find(".//t:profileDesc//t:abstract", ns))
    doi_node = root.find(".//t:idno[@type='DOI']", ns)
    authors = [txt(p) for p in root.findall(".//t:sourceDesc//t:author/t:persName", ns) if txt(p)]
    sections: dict[str, str] = {}
    for div in root.findall(".//t:body/t:div", ns):
        head = txt(div.find("t:head", ns)) or "section"
        body = " ".join(txt(p) for p in div.findall("t:p", ns))
        if body:
            sections[head.lower()] = body
    refs = [txt(b) for b in root.findall(".//t:listBibl/t:biblStruct", ns) if txt(b)]
    full_text = "\n\n".join(f"{k.title()}\n{v}" for k, v in sections.items())
    if abstract:
        full_text = f"Abstract\n{abstract}\n\n" + full_text

    return PdfDocument(
        path=str(path), n_pages=0, title=title, authors=authors,
        doi=(txt(doi_node) if doi_node is not None else ""),
        abstract=abstract[:5000], full_text=full_text[:max_chars],
        sections=sections, references=refs[:200],
        statistics=harvest_statistics(full_text), backend="grobid",
    )


def extract_pdf(path: str | Path, *, max_chars: int = 60000,
                grobid_url: Optional[str] = None) -> Optional[PdfDocument]:
    """Extract a structured :class:`PdfDocument` from one PDF. Prefers GROBID when
    a server is configured, else PyMuPDF. Returns None if no backend can read it."""
    p = Path(path).expanduser()
    if not p.exists():
        return None
    grobid_url = grobid_url or os.environ.get("GROBID_URL", "").strip()
    if grobid_url:
        doc = _extract_grobid(p, grobid_url, max_chars)
        if doc and doc.full_text:
            return doc
    return _extract_fitz(p, max_chars)


def extract_text_from_bytes(raw: bytes, *, max_chars: int = 60000) -> str:
    """Extract reading-order text from in-memory PDF bytes (used for OA PDFs)."""
    try:
        import fitz
        doc = fitz.open(stream=raw, filetype="pdf")
        text = "\n".join(page.get_text("text") for page in doc)
        doc.close()
        return re.sub(r"\n{3,}", "\n\n", text).strip()[:max_chars]
    except Exception:  # noqa: BLE001
        return ""


def extract_dir(folder: str | Path, *, max_chars: int = 60000) -> list[PdfDocument]:
    """Extract every ``*.pdf`` under *folder* (recursively)."""
    base = Path(folder).expanduser()
    out: list[PdfDocument] = []
    if not base.exists():
        return out
    for pdf in sorted(base.rglob("*.pdf")):
        doc = extract_pdf(pdf, max_chars=max_chars)
        if doc:
            out.append(doc)
    return out


# ── Matching PDFs to records + a retriever ───────────────────────────────────
def _norm_title(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def match_documents(docs: list[PdfDocument], records: list[Record]) -> dict[str, PdfDocument]:
    """Map ``Record.uid`` → best PdfDocument by DOI, then filename, then title."""
    by_doi: dict[str, PdfDocument] = {}
    by_title: dict[str, PdfDocument] = {}
    for d in docs:
        if d.doi:
            by_doi[d.doi.lower()] = d
        if d.title:
            by_title[_norm_title(d.title)] = d
    out: dict[str, PdfDocument] = {}
    for r in records:
        hit = None
        if r.doi and r.doi.lower() in by_doi:
            hit = by_doi[r.doi.lower()]
        if hit is None and r.title:
            nt = _norm_title(r.title)
            hit = by_title.get(nt)
            if hit is None:                       # filename fuzzy contains
                for d in docs:
                    stem = _norm_title(Path(d.path).stem)
                    if nt and (nt[:40] in stem or stem[:40] in nt):
                        hit = d
                        break
        if hit is not None:
            out[r.uid] = hit
    return out


class LocalPdfFullTextRetriever:
    """Full-text retriever backed by a folder of PDFs the reviewer already has.

    Extracts every PDF once, matches each record to its PDF (DOI/title/filename),
    and serves the structured full text. Optionally chains to a fallback retriever
    (e.g. the OA/PMC :class:`HttpFullTextRetriever`) for records with no local PDF.
    """

    def __init__(self, folder: str | Path, *, fallback: Optional[FullTextRetriever] = None,
                 max_chars: int = 60000):
        self.folder = folder
        self.fallback = fallback
        self.max_chars = max_chars
        self._docs = extract_dir(folder, max_chars=max_chars)
        self._by_uid: dict[str, PdfDocument] = {}

    def index(self, records: list[Record]) -> int:
        """Pre-match the extracted PDFs against the record set; return match count."""
        self._by_uid = match_documents(self._docs, records)
        return len(self._by_uid)

    def retrieve(self, record: Record) -> FullText:
        doc = self._by_uid.get(record.uid)
        if doc is None:
            doc = next((d for d in self._docs
                        if (record.doi and d.doi and d.doi.lower() == record.doi.lower())), None)
        if doc is not None and doc.full_text:
            return FullText(text=doc.as_working_text(self.max_chars), retrieved=True,
                            source="local-pdf")
        if self.fallback is not None:
            return self.fallback.retrieve(record)
        if record.abstract:
            return FullText(text=record.abstract, retrieved=False, source="abstract")
        return FullText(text="", retrieved=False, source="none")
