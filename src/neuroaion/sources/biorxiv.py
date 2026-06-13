"""bioRxiv / medRxiv preprints via the Europe PMC preprint index.

The native bioRxiv API only supports date-window listing, not keyword search,
so we query Europe PMC restricted to preprint sources — this gives keyword
search over bioRxiv + medRxiv with abstracts.
"""
from __future__ import annotations

from ..models import Record
from .base import clean, http_get

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def search(query: str, retmax: int = 200, **_) -> list[Record]:
    scoped = f"({query}) AND (SRC:PPR)"  # PPR = preprints
    params = {"query": scoped, "format": "json", "pageSize": min(retmax, 1000),
              "resultType": "core"}
    data = http_get(BASE, params).json()
    out: list[Record] = []
    for r in data.get("resultList", {}).get("result", []):
        publisher = clean(r.get("publisher", "")).lower()
        if "biorxiv" not in publisher and "medrxiv" not in publisher and r.get("source") != "PPR":
            continue
        authors = [clean(a.get("fullName", "")) for a in
                   (r.get("authorList", {}) or {}).get("author", [])]
        authors = [a for a in authors if a]
        try:
            year = int(r.get("pubYear")) if r.get("pubYear") else None
        except (ValueError, TypeError):
            year = None
        out.append(Record(
            source="biorxiv",
            source_id=str(r.get("id", "")),
            doi=clean(r.get("doi", "")),
            title=clean(r.get("title", "")),
            abstract=clean(r.get("abstractText", "")),
            authors=authors,
            year=year,
            journal=clean(r.get("publisher", "")) or "preprint",
            url=f"https://doi.org/{r.get('doi','')}" if r.get("doi") else "",
        ))
    return out
