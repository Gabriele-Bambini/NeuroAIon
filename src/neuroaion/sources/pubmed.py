"""PubMed via NCBI E-utilities (esearch + efetch). No key required (key raises limits)."""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET

from .. import config
from ..models import Record
from .base import clean, http_get

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_PER_CALL = 200
_MAX_PAGES = 25


def search(query: str, retmax: int = 200, **_) -> list[Record]:
    per_call = min(retmax, _PER_CALL)
    ids: list[str] = []
    seen: set[str] = set()
    retstart = 0
    for _page in range(_MAX_PAGES):
        params = {"db": "pubmed", "term": query, "retmax": per_call,
                  "retstart": retstart, "retmode": "json"}
        if config.NCBI_API_KEY:
            params["api_key"] = config.NCBI_API_KEY
        try:
            data = http_get(f"{EUTILS}/esearch.fcgi", params).json()
        except Exception:  # noqa: BLE001 — stop paging, return what we have
            break
        page_ids = data.get("esearchresult", {}).get("idlist", [])
        if not page_ids:
            break
        new = [i for i in page_ids if i not in seen]
        for i in new:
            seen.add(i)
        ids.extend(new)
        if len(ids) >= retmax or len(page_ids) < per_call or not new:
            break
        retstart += per_call
        time.sleep(0.34)  # respect 3 req/s without a key
    ids = ids[:retmax]
    if not ids:
        return []
    time.sleep(0.34)  # respect 3 req/s without a key
    # efetch caps the URL length; fetch details in batches.
    out: list[Record] = []
    for start in range(0, len(ids), _PER_CALL):
        batch = ids[start:start + _PER_CALL]
        try:
            out.extend(_fetch_details(batch))
        except Exception:  # noqa: BLE001
            break
        if start + _PER_CALL < len(ids):
            time.sleep(0.34)
    return out


def _fetch_details(pmids: list[str]) -> list[Record]:
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    if config.NCBI_API_KEY:
        params["api_key"] = config.NCBI_API_KEY
    xml = http_get(f"{EUTILS}/efetch.fcgi", params, accept="application/xml").text
    root = ET.fromstring(xml)
    out: list[Record] = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID", default="")
        title = clean(art.findtext(".//ArticleTitle"))
        abstract = " ".join(clean(a.text) for a in art.findall(".//AbstractText") if a.text)
        journal = clean(art.findtext(".//Journal/Title"))
        year_txt = art.findtext(".//JournalIssue/PubDate/Year") or art.findtext(".//PubDate/Year")
        try:
            year = int(year_txt) if year_txt else None
        except ValueError:
            year = None
        authors = []
        for a in art.findall(".//Author"):
            last = a.findtext("LastName")
            init = a.findtext("Initials")
            if last:
                authors.append(f"{last} {init}".strip())
        doi = ""
        for idn in art.findall(".//ArticleId"):
            if idn.get("IdType") == "doi":
                doi = clean(idn.text)
        out.append(Record(
            source="pubmed", source_id=pmid, doi=doi, title=title, abstract=abstract,
            authors=authors, year=year, journal=journal,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        ))
    return out
