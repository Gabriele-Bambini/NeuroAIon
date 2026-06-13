"""Semantic Scholar Graph API — broad scholarly search. Free; optional key raises limits."""
from __future__ import annotations

import os

from ..models import Record
from .base import clean, http_get

BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = "title,abstract,year,venue,authors,externalIds,openAccessPdf,url"


def search(query: str, retmax: int = 200, **_) -> list[Record]:
    headers_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    params = {"query": query, "limit": min(retmax, 100), "fields": _FIELDS}
    # http_get sets its own headers; the optional key is passed if present.
    url = BASE
    if headers_key:
        params["x-api-key"] = headers_key  # tolerated as query by the gateway
    data = http_get(url, params).json()
    out: list[Record] = []
    for p in data.get("data", []) or []:
        ext = p.get("externalIds", {}) or {}
        oa = (p.get("openAccessPdf") or {}).get("url", "")
        authors = [clean(a.get("name", "")) for a in p.get("authors", [])]
        out.append(Record(
            source="semanticscholar",
            source_id=clean(p.get("paperId", "")),
            doi=clean(ext.get("DOI", "")),
            title=clean(p.get("title", "")),
            abstract=clean(p.get("abstract", "")),
            authors=[a for a in authors if a],
            year=p.get("year"),
            journal=clean(p.get("venue", "")),
            url=oa or clean(p.get("url", "")),
        ))
    return out
