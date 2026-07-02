"""Europe PMC REST API (covers PubMed, PMC, preprints, Agricola)."""
from __future__ import annotations

from ..models import Record
from .base import clean, http_get

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_PAGE_SIZE = 1000
_MAX_PAGES = 25


def _parse(r: dict) -> Record:
    authors = []
    for a in (r.get("authorList", {}) or {}).get("author", []):
        name = a.get("fullName") or a.get("lastName") or ""
        if name:
            authors.append(name)
    try:
        year = int(r.get("pubYear")) if r.get("pubYear") else None
    except (ValueError, TypeError):
        year = None
    doi = clean(r.get("doi", ""))
    pmid = clean(str(r.get("pmid", "")))
    pmcid = clean(str(r.get("pmcid", "")))
    ids: dict[str, str] = {}
    if doi:
        ids["doi"] = doi
    if pmid:
        ids["pmid"] = pmid
    if pmcid:
        ids["pmcid"] = pmcid
    return Record(
        source="europepmc",
        source_id=str(r.get("id", "")),
        doi=doi,
        pmid=pmid,
        ids=ids,
        title=clean(r.get("title", "")),
        abstract=clean(r.get("abstractText", "")),
        authors=authors,
        year=year,
        journal=clean(r.get("journalTitle", "")),
        url=f"https://europepmc.org/abstract/{r.get('source','MED')}/{r.get('id','')}",
    )


def search(query: str, retmax: int = 200, **_) -> list[Record]:
    page_size = min(retmax, _PAGE_SIZE)
    out: list[Record] = []
    seen: set[str] = set()
    cursor = "*"
    for _page in range(_MAX_PAGES):
        params = {"query": query, "format": "json", "pageSize": page_size,
                  "resultType": "core", "cursorMark": cursor}
        try:
            data = http_get(BASE, params).json()
        except Exception:  # noqa: BLE001 — stop paging, return what we have
            break
        results = data.get("resultList", {}).get("result", [])
        if not results:
            break
        for r in results:
            rec = _parse(r)
            key = rec.source_id or rec.uid
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)
            if len(out) >= retmax:
                return out[:retmax]
        nxt = data.get("nextCursorMark")
        if not nxt or nxt == cursor:
            break
        cursor = nxt
    return out[:retmax]
