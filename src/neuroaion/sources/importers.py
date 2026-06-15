"""Citation-file importers — the legitimate way to use subscription databases.

A reviewer with institutional access runs the search in their own authenticated
browser session on each database (Scopus, Web of Science, ScienceDirect, Ovid,
EBSCO, PubMed, …) and **exports** the results. This module ingests those exports
so the records flow into the normal PRISMA pipeline (de-duplication, screening,
…). No credentials are ever handled by the engine, and no publisher terms are
violated — this is exactly how PRISMA reviews are conducted.

Supported formats (auto-detected): RIS (``.ris``), BibTeX (``.bib``), PubMed /
MEDLINE / NBIB (``.nbib``), EndNote XML (``.xml``), and generic CSV/TSV
(``.csv``/``.tsv``) with best-effort column mapping. Every parser returns a list
of :class:`~neuroaion.models.Record`; everything is pure text processing and
fully offline-testable.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Iterable, Optional

from ..models import Record

# RIS reference-type → our entry_type.
_RIS_TYPE = {
    "JOUR": "article", "EJOUR": "article", "CONF": "inproceedings",
    "CPAPER": "inproceedings", "BOOK": "book", "CHAP": "inbook",
    "THES": "phdthesis", "RPRT": "techreport", "UNPB": "preprint",
}
_BIBTEX_TYPE = {
    "article": "article", "inproceedings": "inproceedings", "conference": "inproceedings",
    "book": "book", "inbook": "inbook", "incollection": "inbook",
    "phdthesis": "phdthesis", "mastersthesis": "mastersthesis",
    "techreport": "techreport", "misc": "misc", "unpublished": "preprint",
}


def _year(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    m = re.search(r"(19|20)\d{2}", str(value))
    return int(m.group(0)) if m else None


def _doi(value: Optional[str]) -> str:
    if not value:
        return ""
    v = str(value).strip()
    v = re.sub(r"^https?://(dx\.)?doi\.org/", "", v, flags=re.I)
    v = re.sub(r"^doi:\s*", "", v, flags=re.I)
    return v.strip()


def _clean(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


# ── RIS ──────────────────────────────────────────────────────────────────────
def parse_ris(text: str) -> list[Record]:
    records: list[Record] = []
    cur: dict[str, list[str]] = {}

    def flush() -> None:
        if not cur:
            return
        def one(tag: str) -> str:
            return _clean(cur.get(tag, [""])[0]) if cur.get(tag) else ""
        title = one("TI") or one("T1") or one("CT")
        journal = one("JO") or one("JF") or one("T2") or one("JA")
        pages = ""
        if cur.get("SP"):
            pages = _clean(cur["SP"][0]) + (f"-{_clean(cur['EP'][0])}" if cur.get("EP") else "")
        ty = one("TY").upper()
        records.append(Record(
            source="import:ris",
            source_id=one("AN") or one("ID") or one("DO"),
            doi=_doi(one("DO")),
            pmid=one("PM") or (one("AN") if one("DB").upper().startswith("MEDLIN") else ""),
            title=title,
            abstract=_clean(" ".join(cur.get("AB", []) or cur.get("N2", []))),
            authors=[_clean(a) for a in (cur.get("AU", []) or cur.get("A1", [])) if _clean(a)],
            year=_year(one("PY") or one("Y1") or one("DA")),
            journal=journal,
            journal_abbrev=one("JA") or one("J2"),
            volume=one("VL"), issue=one("IS"), pages=pages,
            entry_type=_RIS_TYPE.get(ty, "article"),
            url=one("UR") or one("L1"),
            raw={"format": "ris", "TY": ty, "provider": one("DB") or one("DP")},
        ))
        cur.clear()

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        m = re.match(r"^([A-Z][A-Z0-9])  - ?(.*)$", line)
        if m:
            tag, val = m.group(1), m.group(2)
            if tag == "ER":
                flush()
            else:
                cur.setdefault(tag, []).append(val)
        elif line.strip() and cur:
            # Continuation of the previous tag's last value.
            last = next(reversed(cur))
            cur[last][-1] += " " + line.strip()
    flush()
    return [r for r in records if r.title or r.doi]


# ── BibTeX ───────────────────────────────────────────────────────────────────
def _split_bibtex_entries(text: str) -> list[tuple[str, str, str]]:
    """Yield (entry_type, citekey, body) for each @type{...} block."""
    out, i, n = [], 0, len(text)
    while True:
        at = text.find("@", i)
        if at < 0:
            break
        brace = text.find("{", at)
        if brace < 0:
            break
        etype = text[at + 1:brace].strip().lower()
        # Walk braces to the matching close.
        depth, j = 0, brace
        while j < n:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = text[brace + 1:j]
        key, _, rest = body.partition(",")
        out.append((etype, key.strip(), rest))
        i = j + 1
    return out


def _parse_bibtex_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    i, n = 0, len(body)
    while i < n:
        eq = body.find("=", i)
        if eq < 0:
            break
        name = body[i:eq].strip().strip(",").lower()
        j = eq + 1
        while j < n and body[j] in " \t\r\n":
            j += 1
        if j >= n:
            break
        if body[j] == "{":
            depth, k = 0, j
            while k < n:
                if body[k] == "{":
                    depth += 1
                elif body[k] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            val = body[j + 1:k]
            i = k + 1
        elif body[j] == '"':
            k = j + 1
            while k < n and body[k] != '"':
                k += 1
            val = body[j + 1:k]
            i = k + 1
        else:
            k = j
            while k < n and body[k] not in ",\n":
                k += 1
            val = body[j:k]
            i = k + 1
        # Skip trailing comma.
        while i < n and body[i] in " \t\r\n,":
            i += 1
        if name:
            fields[name] = re.sub(r"[{}]", "", val).strip()
    return fields


def parse_bibtex(text: str) -> list[Record]:
    records: list[Record] = []
    for etype, key, body in _split_bibtex_entries(text):
        if etype in ("comment", "preamble", "string"):
            continue
        f = _parse_bibtex_fields(body)
        authors = [a.strip() for a in re.split(r"\s+and\s+", f.get("author", "")) if a.strip()]
        pages = f.get("pages", "").replace("--", "-")
        records.append(Record(
            source="import:bibtex",
            source_id=key or f.get("doi", ""),
            doi=_doi(f.get("doi")),
            pmid=f.get("pmid", ""),
            title=_clean(f.get("title")),
            abstract=_clean(f.get("abstract")),
            authors=authors,
            year=_year(f.get("year") or f.get("date")),
            journal=_clean(f.get("journal") or f.get("journaltitle") or f.get("booktitle")),
            volume=f.get("volume", ""), issue=f.get("number", ""), pages=pages,
            entry_type=_BIBTEX_TYPE.get(etype, "article"),
            url=f.get("url", "") or (f"https://doi.org/{_doi(f.get('doi'))}" if f.get("doi") else ""),
            raw={"format": "bibtex", "bibtype": etype, "citekey": key},
        ))
    return [r for r in records if r.title or r.doi]


# ── PubMed / MEDLINE / NBIB ──────────────────────────────────────────────────
def parse_medline(text: str) -> list[Record]:
    records: list[Record] = []
    cur: dict[str, list[str]] = {}

    def flush() -> None:
        if not cur:
            return
        def one(tag: str) -> str:
            return _clean(cur[tag][0]) if cur.get(tag) else ""
        # DOI may be in AID ("10.xxxx [doi]") or LID.
        doi = ""
        for tag in ("AID", "LID"):
            for v in cur.get(tag, []):
                if "[doi]" in v.lower():
                    doi = _doi(v.split()[0])
                    break
            if doi:
                break
        pages = one("PG")
        records.append(Record(
            source="import:pubmed",
            source_id=one("PMID"),
            doi=doi,
            pmid=one("PMID"),
            title=_clean(" ".join(cur.get("TI", []))),
            abstract=_clean(" ".join(cur.get("AB", []))),
            authors=[_clean(a) for a in cur.get("FAU", []) or cur.get("AU", []) if _clean(a)],
            year=_year(one("DP")),
            journal=one("JT"),
            journal_abbrev=one("TA"),
            volume=one("VI"), issue=one("IP"), pages=pages,
            entry_type="article",
            url=f"https://pubmed.ncbi.nlm.nih.gov/{one('PMID')}/" if one("PMID") else "",
            raw={"format": "medline"},
        ))
        cur.clear()

    # MEDLINE records are separated by a blank line.
    for block in re.split(r"\n[ \t]*\n", text.strip()):
        cur.clear()
        last_tag = None
        for line in block.splitlines():
            m = re.match(r"^([A-Z]{2,4})\s*-\s?(.*)$", line)
            if m:
                last_tag, val = m.group(1), m.group(2)
                cur.setdefault(last_tag, []).append(val)
            elif line.startswith("      ") and last_tag:   # 6-space continuation
                cur[last_tag][-1] += " " + line.strip()
        if cur:
            flush()
    return [r for r in records if r.title or r.doi or r.pmid]


# ── EndNote XML ──────────────────────────────────────────────────────────────
def parse_endnote_xml(text: str) -> list[Record]:
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    def txt(node) -> str:
        if node is None:
            return ""
        return _clean("".join(node.itertext()))

    records: list[Record] = []
    for rec in root.iter("record"):
        title = txt(rec.find("./titles/title"))
        journal = txt(rec.find("./periodical/full-title")) or txt(rec.find("./titles/secondary-title"))
        authors = [txt(a) for a in rec.findall("./contributors/authors/author") if txt(a)]
        doi = _doi(txt(rec.find("./electronic-resource-num")))
        url = txt(rec.find("./urls/related-urls/url")) or txt(rec.find("./urls/web-urls/url"))
        records.append(Record(
            source="import:endnote",
            source_id=txt(rec.find("./accession-num")) or doi,
            doi=doi,
            pmid=txt(rec.find("./accession-num")) if "pubmed" in txt(rec.find("./remote-database-name")).lower() else "",
            title=title,
            abstract=txt(rec.find("./abstract")),
            authors=authors,
            year=_year(txt(rec.find("./dates/year"))),
            journal=journal,
            volume=txt(rec.find("./volume")), issue=txt(rec.find("./number")),
            pages=txt(rec.find("./pages")),
            entry_type="article",
            url=url,
            raw={"format": "endnote"},
        ))
    return [r for r in records if r.title or r.doi]


# ── Generic CSV / TSV ────────────────────────────────────────────────────────
_CSV_ALIASES = {
    "title": ["title", "article title", "document title", "ti"],
    "abstract": ["abstract", "ab"],
    "authors": ["authors", "author", "author names", "au", "author full names"],
    "year": ["year", "publication year", "py", "date"],
    "doi": ["doi", "di"],
    "pmid": ["pmid", "pubmed id", "pubmedid"],
    "journal": ["journal", "source title", "source", "publication title", "so"],
    "volume": ["volume", "vol", "vl"],
    "issue": ["issue", "is"],
    "pages": ["pages", "page start", "bp"],
    "url": ["url", "link", "doi link"],
}


def _map_header(fieldnames: Iterable[str]) -> dict[str, str]:
    lower = {(h or "").strip().lower(): h for h in fieldnames}
    out: dict[str, str] = {}
    for canon, aliases in _CSV_ALIASES.items():
        for a in aliases:
            if a in lower:
                out[canon] = lower[a]
                break
    return out


def parse_csv(text: str) -> list[Record]:
    sniff = text[:4096]
    delim = "\t" if sniff.count("\t") > sniff.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    if not reader.fieldnames:
        return []
    cmap = _map_header(reader.fieldnames)
    if "title" not in cmap and "doi" not in cmap:
        return []
    records: list[Record] = []

    def g(row, key):
        col = cmap.get(key)
        return _clean(row.get(col, "")) if col else ""

    for row in reader:
        au = g(row, "authors")
        authors = [a.strip() for a in re.split(r"\s*;\s*|\s+and\s+", au) if a.strip()] if au else []
        records.append(Record(
            source="import:csv",
            source_id=g(row, "doi") or g(row, "pmid"),
            doi=_doi(g(row, "doi")),
            pmid=g(row, "pmid"),
            title=g(row, "title"),
            abstract=g(row, "abstract"),
            authors=authors,
            year=_year(g(row, "year")),
            journal=g(row, "journal"),
            volume=g(row, "volume"), issue=g(row, "issue"), pages=g(row, "pages"),
            entry_type="article",
            url=g(row, "url"),
            raw={"format": "csv"},
        ))
    return [r for r in records if r.title or r.doi]


# ── Dispatch ─────────────────────────────────────────────────────────────────
def _sniff_format(text: str, suffix: str) -> str:
    s = suffix.lower().lstrip(".")
    if s in ("ris", "bib", "bibtex", "nbib", "csv", "tsv", "xml"):
        return {"bibtex": "bib"}.get(s, s)
    head = text.lstrip()[:600]
    if head.startswith("<") and ("<record" in text[:5000] or "<xml" in head.lower()):
        return "xml"
    if head.startswith("@") and "{" in head:
        return "bib"
    if re.search(r"^PMID\s*-\s*\d", text, re.M):
        return "nbib"
    if re.search(r"^TY  - ", text, re.M):
        return "ris"
    if "," in head.splitlines()[0] if head.splitlines() else False:
        return "csv"
    return "ris"


_PARSERS = {
    "ris": parse_ris, "bib": parse_bibtex, "nbib": parse_medline,
    "xml": parse_endnote_xml, "csv": parse_csv, "tsv": parse_csv,
}


def parse_text(text: str, fmt: str) -> list[Record]:
    """Parse citation text in an explicit format ('ris'|'bib'|'nbib'|'xml'|'csv')."""
    parser = _PARSERS.get(fmt.lower())
    if parser is None:
        raise ValueError(f"unknown citation format: {fmt!r}")
    return parser(text)


def import_file(path: str | Path) -> list[Record]:
    """Auto-detect and parse a single citation-export file into Records."""
    p = Path(path).expanduser()
    text = p.read_text(encoding="utf-8", errors="replace")
    fmt = _sniff_format(text, p.suffix)
    recs = parse_text(text, fmt)
    # Tag provenance with the originating file so the search log is auditable.
    for r in recs:
        r.raw.setdefault("import_file", p.name)
    return recs


def import_paths(paths: Iterable[str | Path]) -> list[Record]:
    """Import and concatenate Records from many citation-export files."""
    out: list[Record] = []
    for p in paths:
        try:
            out.extend(import_file(p))
        except Exception:  # noqa: BLE001 — one bad file must not abort the import
            continue
    return out
