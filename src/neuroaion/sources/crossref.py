"""Crossref REST API — broad scholarly metadata across publishers."""
from __future__ import annotations

from .. import config
from ..models import Record
from .base import clean, http_get

BASE = "https://api.crossref.org/works"


def search(query: str, retmax: int = 200, **_) -> list[Record]:
    params = {"query": query, "rows": min(retmax, 100), "mailto": config.CONTACT_EMAIL,
              "select": "DOI,title,abstract,author,issued,container-title,URL"}
    data = http_get(BASE, params).json()
    out: list[Record] = []
    for item in data.get("message", {}).get("items", []):
        title = clean(" ".join(item.get("title", [])))
        if not title:
            continue
        authors = [clean(f"{a.get('family','')} {a.get('given','')}") for a in item.get("author", [])]
        authors = [a for a in authors if a]
        year = None
        parts = item.get("issued", {}).get("date-parts", [[None]])
        if parts and parts[0] and parts[0][0]:
            year = parts[0][0]
        out.append(Record(
            source="crossref",
            source_id=clean(item.get("DOI", "")),
            doi=clean(item.get("DOI", "")),
            title=title,
            abstract=clean(item.get("abstract", "")),
            authors=authors,
            year=year,
            journal=clean(" ".join(item.get("container-title", []))),
            url=clean(item.get("URL", "")),
        ))
    return out
