"""Europe PMC REST API (covers PubMed, PMC, preprints, Agricola)."""
from __future__ import annotations

from ..models import Record
from .base import clean, http_get

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def search(query: str, retmax: int = 200, **_) -> list[Record]:
    params = {"query": query, "format": "json", "pageSize": min(retmax, 1000),
              "resultType": "core"}
    data = http_get(BASE, params).json()
    out: list[Record] = []
    for r in data.get("resultList", {}).get("result", []):
        authors = []
        for a in (r.get("authorList", {}) or {}).get("author", []):
            name = a.get("fullName") or a.get("lastName") or ""
            if name:
                authors.append(name)
        try:
            year = int(r.get("pubYear")) if r.get("pubYear") else None
        except (ValueError, TypeError):
            year = None
        out.append(Record(
            source="europepmc",
            source_id=str(r.get("id", "")),
            doi=clean(r.get("doi", "")),
            title=clean(r.get("title", "")),
            abstract=clean(r.get("abstractText", "")),
            authors=authors,
            year=year,
            journal=clean(r.get("journalTitle", "")),
            url=f"https://europepmc.org/abstract/{r.get('source','MED')}/{r.get('id','')}",
        ))
    return out
