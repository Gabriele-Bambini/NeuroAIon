"""arXiv API — open preprints (Atom XML). Free, no key."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ..models import Record
from .base import clean, http_get

BASE = "http://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"


def search(query: str, retmax: int = 200, **_) -> list[Record]:
    params = {"search_query": f"all:{query}", "start": 0, "max_results": min(retmax, 100)}
    xml = http_get(BASE, params, accept="application/atom+xml").text
    root = ET.fromstring(xml)
    out: list[Record] = []
    for entry in root.findall(f"{_ATOM}entry"):
        title = clean(entry.findtext(f"{_ATOM}title"))
        summary = clean(entry.findtext(f"{_ATOM}summary"))
        link = clean(entry.findtext(f"{_ATOM}id"))
        published = entry.findtext(f"{_ATOM}published") or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [clean(a.findtext(f"{_ATOM}name")) for a in entry.findall(f"{_ATOM}author")]
        doi = clean(entry.findtext("{http://arxiv.org/schemas/atom}doi") or "")
        arxiv_id = link.rsplit("/", 1)[-1]
        ids: dict[str, str] = {}
        if arxiv_id:
            ids["arxiv"] = arxiv_id
        if doi:
            ids["doi"] = doi
        out.append(Record(
            source="arxiv", source_id=arxiv_id, doi=doi, ids=ids,
            title=title, abstract=summary, authors=[a for a in authors if a],
            year=year, journal="arXiv", url=link,
        ))
    return out
