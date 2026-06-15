"""Crossref REST API — broad scholarly metadata across publishers."""
from __future__ import annotations

from .. import config
from ..models import Record
from .base import clean, http_get

BASE = "https://api.crossref.org/works"
_ROWS = 200
_MAX_PAGES = 25


def _parse(item: dict) -> Record | None:
    title = clean(" ".join(item.get("title", [])))
    if not title:
        return None
    authors = [clean(f"{a.get('family','')} {a.get('given','')}") for a in item.get("author", [])]
    authors = [a for a in authors if a]
    year = None
    parts = item.get("issued", {}).get("date-parts", [[None]])
    if parts and parts[0] and parts[0][0]:
        year = parts[0][0]
    return Record(
        source="crossref",
        source_id=clean(item.get("DOI", "")),
        doi=clean(item.get("DOI", "")),
        title=title,
        abstract=clean(item.get("abstract", "")),
        authors=authors,
        year=year,
        journal=clean(" ".join(item.get("container-title", []))),
        url=clean(item.get("URL", "")),
    )


def search(query: str, retmax: int = 200, **_) -> list[Record]:
    rows = min(retmax, _ROWS)
    out: list[Record] = []
    seen: set[str] = set()
    cursor = "*"
    for _page in range(_MAX_PAGES):
        params = {"query": query, "rows": rows, "mailto": config.CONTACT_EMAIL,
                  "select": "DOI,title,abstract,author,issued,container-title,URL",
                  "cursor": cursor}
        try:
            data = http_get(BASE, params).json()
        except Exception:  # noqa: BLE001 — stop paging, return what we have
            break
        message = data.get("message", {}) or {}
        items = message.get("items", [])
        if not items:
            break
        for item in items:
            rec = _parse(item)
            if rec is None:
                continue
            key = rec.doi or rec.uid
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)
            if len(out) >= retmax:
                return out[:retmax]
        cursor = message.get("next-cursor")
        if not cursor:
            break
    return out[:retmax]
