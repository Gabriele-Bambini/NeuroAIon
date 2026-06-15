"""OpenAlex API — open catalogue of scholarly works."""
from __future__ import annotations

from .. import config
from ..models import Record
from .base import clean, http_get

BASE = "https://api.openalex.org/works"


def _deinvert(idx: dict | None) -> str:
    """OpenAlex returns abstracts as an inverted index; reconstruct the text."""
    if not idx:
        return ""
    positions: list[tuple[int, str]] = []
    for word, locs in idx.items():
        for p in locs:
            positions.append((p, word))
    positions.sort()
    return " ".join(w for _, w in positions)


_PER_PAGE = 200
_MAX_PAGES = 25


def _parse(w: dict) -> Record:
    authors = [clean(a.get("author", {}).get("display_name", ""))
               for a in w.get("authorships", [])]
    authors = [a for a in authors if a]
    doi = clean((w.get("doi") or "").replace("https://doi.org/", ""))
    return Record(
        source="openalex",
        source_id=clean(w.get("id", "")),
        doi=doi,
        title=clean(w.get("title", "")),
        abstract=_deinvert(w.get("abstract_inverted_index")),
        authors=authors,
        year=w.get("publication_year"),
        journal=clean((w.get("primary_location", {}) or {}).get("source", {}).get("display_name", "")
                      if w.get("primary_location") else ""),
        url=clean(w.get("id", "")),
    )


def search(query: str, retmax: int = 200, **_) -> list[Record]:
    per_page = min(retmax, _PER_PAGE)
    out: list[Record] = []
    seen: set[str] = set()
    cursor = "*"
    for _page in range(_MAX_PAGES):
        params = {"search": query, "per-page": per_page,
                  "mailto": config.CONTACT_EMAIL, "cursor": cursor}
        try:
            data = http_get(BASE, params).json()
        except Exception:  # noqa: BLE001 — stop paging, return what we have
            break
        results = data.get("results", [])
        if not results:
            break
        for w in results:
            rec = _parse(w)
            key = rec.source_id or rec.uid
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)
            if len(out) >= retmax:
                return out[:retmax]
        cursor = (data.get("meta", {}) or {}).get("next_cursor")
        if not cursor:
            break
    return out[:retmax]
