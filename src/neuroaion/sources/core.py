"""CORE v3 API — open-access aggregator (290M+ papers) for identification.

Free, ToS-compliant. CORE allows limited keyless use; a key (CORE_API_KEY)
raises the rate/volume limits. The key is read defensively from the
environment so config.py needs no change. If no key is present and the API
responds 401, we return [] rather than failing the whole review.
"""
from __future__ import annotations

import os

from ..models import Record
from .base import clean, http_get

BASE = "https://api.core.ac.uk/v3/search/works"
_LIMIT = 100          # CORE caps limit at 100 per page
_MAX_PAGES = 25


def _authors(work: dict) -> list[str]:
    out: list[str] = []
    for a in work.get("authors", []) or []:
        if isinstance(a, dict):
            name = a.get("name", "")
        else:
            name = str(a)
        name = clean(name)
        if name:
            out.append(name)
    return out


def _journal(work: dict) -> str:
    journals = work.get("journals") or []
    if journals:
        j = journals[0]
        if isinstance(j, dict):
            title = clean(j.get("title", ""))
            if title:
                return title
    return clean(work.get("publisher", ""))


def _url(work: dict) -> str:
    url = clean(work.get("downloadUrl", "") or "")
    if url:
        return url
    for link in work.get("links", []) or []:
        if isinstance(link, dict) and link.get("url"):
            return clean(link["url"])
    doi = clean(work.get("doi", ""))
    return f"https://doi.org/{doi}" if doi else ""


def _parse(work: dict) -> Record:
    return Record(
        source="core",
        source_id=clean(str(work.get("id", ""))),
        doi=clean(work.get("doi", "") or ""),
        title=clean(work.get("title", "")),
        abstract=clean(work.get("abstract", "") or ""),
        authors=_authors(work),
        year=work.get("yearPublished"),
        journal=_journal(work),
        url=_url(work),
    )


def search(query: str, retmax: int = 200, **_) -> list[Record]:
    api_key = os.environ.get("CORE_API_KEY", "").strip()
    limit = min(retmax, _LIMIT)
    out: list[Record] = []
    seen: set[str] = set()
    offset = 0
    for _page in range(_MAX_PAGES):
        params = {"q": query, "limit": limit, "offset": offset}
        if api_key:
            params["Authorization"] = f"Bearer {api_key}"
        try:
            data = http_get(BASE, params).json()
        except Exception:  # noqa: BLE001 — 401 without key, transient errors, etc.
            break
        results = data.get("results", []) or []
        if not results:
            break
        for work in results:
            rec = _parse(work)
            key = rec.source_id or rec.uid
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)
            if len(out) >= retmax:
                return out[:retmax]
        offset += limit
        total = data.get("totalHits")
        if total is not None and offset >= total:
            break
    return out[:retmax]
