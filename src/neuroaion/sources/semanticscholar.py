"""Semantic Scholar Graph API — broad scholarly search. Free; optional key raises limits."""
from __future__ import annotations

import os

from ..models import Record
from .base import clean, http_get

BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = "title,abstract,year,venue,authors,externalIds,openAccessPdf,url"


_LIMIT = 100
_MAX_PAGES = 25


def _parse(p: dict) -> Record:
    ext = p.get("externalIds", {}) or {}
    oa = (p.get("openAccessPdf") or {}).get("url", "")
    authors = [clean(a.get("name", "")) for a in p.get("authors", [])]
    return Record(
        source="semanticscholar",
        source_id=clean(p.get("paperId", "")),
        doi=clean(ext.get("DOI", "")),
        title=clean(p.get("title", "")),
        abstract=clean(p.get("abstract", "")),
        authors=[a for a in authors if a],
        year=p.get("year"),
        journal=clean(p.get("venue", "")),
        url=oa or clean(p.get("url", "")),
    )


def search(query: str, retmax: int = 200, **_) -> list[Record]:
    headers_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    limit = min(retmax, _LIMIT)
    out: list[Record] = []
    seen: set[str] = set()
    offset = 0
    for _page in range(_MAX_PAGES):
        params = {"query": query, "limit": limit, "offset": offset, "fields": _FIELDS}
        if headers_key:
            params["x-api-key"] = headers_key  # tolerated as query by the gateway
        try:
            data = http_get(BASE, params).json()
        except Exception:  # noqa: BLE001 — stop paging, return what we have
            break
        rows = data.get("data", []) or []
        if not rows:
            break
        for p in rows:
            rec = _parse(p)
            key = rec.source_id or rec.uid
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)
            if len(out) >= retmax:
                return out[:retmax]
        nxt = data.get("next")
        if nxt is None:
            break
        offset = nxt
    return out[:retmax]
