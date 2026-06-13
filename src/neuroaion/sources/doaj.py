"""DOAJ — Directory of Open Access Journals article search. Free, no key."""
from __future__ import annotations

from urllib.parse import quote

from ..models import Record
from .base import clean, http_get

BASE = "https://doaj.org/api/v2/search/articles/"


def search(query: str, retmax: int = 200, **_) -> list[Record]:
    url = BASE + quote(query, safe="")
    data = http_get(url, {"pageSize": min(retmax, 100)}).json()
    out: list[Record] = []
    for item in data.get("results", []):
        b = item.get("bibjson", {})
        doi = ""
        for ident in b.get("identifier", []):
            if ident.get("type", "").lower() == "doi":
                doi = clean(ident.get("id", ""))
        link = ""
        for ln in b.get("link", []):
            if ln.get("url"):
                link = ln["url"]
                break
        authors = [clean(a.get("name", "")) for a in b.get("author", [])]
        try:
            year = int(b.get("year")) if b.get("year") else None
        except (ValueError, TypeError):
            year = None
        out.append(Record(
            source="doaj", source_id=clean(item.get("id", "")), doi=doi,
            title=clean(b.get("title", "")), abstract=clean(b.get("abstract", "")),
            authors=[a for a in authors if a], year=year,
            journal=clean(b.get("journal", {}).get("title", "")), url=link,
        ))
    return out
