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


def search(query: str, retmax: int = 200, **_) -> list[Record]:
    params = {"search": query, "per-page": min(retmax, 200), "mailto": config.CONTACT_EMAIL}
    data = http_get(BASE, params).json()
    out: list[Record] = []
    for w in data.get("results", []):
        authors = [clean(a.get("author", {}).get("display_name", ""))
                   for a in w.get("authorships", [])]
        authors = [a for a in authors if a]
        doi = clean((w.get("doi") or "").replace("https://doi.org/", ""))
        out.append(Record(
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
        ))
    return out
