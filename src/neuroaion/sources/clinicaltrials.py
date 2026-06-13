"""ClinicalTrials.gov API v2 — trial registry (PRISMA "other sources"). Free, no key."""
from __future__ import annotations

from ..models import Record
from .base import clean, http_get

BASE = "https://clinicaltrials.gov/api/v2/studies"


def search(query: str, retmax: int = 200, **_) -> list[Record]:
    params = {"query.term": query, "pageSize": min(retmax, 100), "format": "json"}
    data = http_get(BASE, params).json()
    out: list[Record] = []
    for st in data.get("studies", []):
        ps = st.get("protocolSection", {})
        ident = ps.get("identificationModule", {})
        nct = ident.get("nctId", "")
        title = clean(ident.get("officialTitle") or ident.get("briefTitle", ""))
        summary = clean(ps.get("descriptionModule", {}).get("briefSummary", ""))
        start = ps.get("statusModule", {}).get("startDateStruct", {}).get("date", "")
        year = None
        if start[:4].isdigit():
            year = int(start[:4])
        out.append(Record(
            source="clinicaltrials", source_id=nct, doi="", title=title,
            abstract=summary, authors=[], year=year, journal="ClinicalTrials.gov",
            url=f"https://clinicaltrials.gov/study/{nct}",
        ))
    return out
