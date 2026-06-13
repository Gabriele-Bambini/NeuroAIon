"""PubMed via NCBI E-utilities (esearch + efetch). No key required (key raises limits)."""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET

from .. import config
from ..models import Record
from .base import clean, http_get

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def search(query: str, retmax: int = 200, **_) -> list[Record]:
    params = {"db": "pubmed", "term": query, "retmax": retmax, "retmode": "json"}
    if config.NCBI_API_KEY:
        params["api_key"] = config.NCBI_API_KEY
    data = http_get(f"{EUTILS}/esearch.fcgi", params).json()
    ids = data.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    time.sleep(0.34)  # respect 3 req/s without a key
    return _fetch_details(ids)


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
