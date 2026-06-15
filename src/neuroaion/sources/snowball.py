"""Citation snowballing (citation chasing) — supplementary PRISMA-2020 search.

Forward snowballing finds papers that CITE an included study; backward
snowballing walks an included study's REFERENCE list. OpenAlex is the primary
backend (both directions, free, no key); Crossref is a backward fallback.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .. import config
from ..models import Record
from .base import clean, http_get

OA_WORKS = "https://api.openalex.org/works"
CR_WORKS = "https://api.crossref.org/works"

# OpenAlex caps OR-filters at 50 ids per request.
_OA_BATCH = 50


# ── id / doi normalisation ───────────────────────────────────────────────────
def _norm_doi(value: str | None) -> str:
    """Strip the URL prefix from a DOI, leaving a bare ``10.x`` string."""
    d = clean(value).lower()
    for pre in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(pre):
            d = d[len(pre):]
    return d


def _oa_id(value: str | None) -> str:
    """Reduce an OpenAlex work id to its short ``W…`` form."""
    v = clean(value)
    return v.rsplit("/", 1)[-1] if v else ""


def _is_oa_id(value: str | None) -> bool:
    return _oa_id(value).startswith("W")


def _resolve_work(work_id_or_doi: str) -> dict:
    """Fetch a single OpenAlex work, accepting a DOI or an OpenAlex id."""
    raw = clean(work_id_or_doi)
    if _is_oa_id(raw):
        path = _oa_id(raw)
    else:  # treat as a DOI in any form
        path = "https://doi.org/" + _norm_doi(raw)
    params = {"mailto": config.CONTACT_EMAIL}
    return http_get(f"{OA_WORKS}/{path}", params).json() or {}


# ── OpenAlex Record building ─────────────────────────────────────────────────
def _deinvert(idx: dict | None) -> str:
    """OpenAlex returns abstracts as an inverted index; reconstruct the text."""
    if not idx:
        return ""
    positions: list[tuple[int, str]] = []
    for word, locs in idx.items():
        for p in locs or []:
            positions.append((p, word))
    positions.sort()
    return " ".join(w for _, w in positions)


def _record_from_oa(w: dict, source: str) -> Record:
    w = w or {}
    authors = [clean((a.get("author") or {}).get("display_name", ""))
               for a in (w.get("authorships") or [])]
    authors = [a for a in authors if a]
    loc = w.get("primary_location") or {}
    journal = clean(((loc.get("source") or {}).get("display_name", "")) if loc else "")
    return Record(
        source=source,
        source_id=clean(w.get("id", "")),
        doi=_norm_doi(w.get("doi")),
        title=clean(w.get("title", "")),
        abstract=_deinvert(w.get("abstract_inverted_index")),
        authors=authors,
        year=w.get("publication_year"),
        journal=journal,
        url=clean(w.get("id", "")),
        raw=w,
    )


def _chunk(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


# ── backward (references) ────────────────────────────────────────────────────
def references_openalex(work_id_or_doi: str, *, retmax: int = 100) -> list[Record]:
    """Backward snowballing via OpenAlex ``referenced_works``."""
    work = _resolve_work(work_id_or_doi)
    ref_ids = [_oa_id(r) for r in (work.get("referenced_works") or [])]
    ref_ids = [r for r in ref_ids if r][:retmax]
    out: list[Record] = []
    for batch in _chunk(ref_ids, _OA_BATCH):
        params = {
            "filter": "openalex_id:" + "|".join(batch),
            "per-page": min(len(batch), 200),
            "mailto": config.CONTACT_EMAIL,
        }
        data = http_get(OA_WORKS, params).json() or {}
        for w in data.get("results", []) or []:
            out.append(_record_from_oa(w, "snowball:backward"))
    return out[:retmax]


def references_crossref(doi: str, *, retmax: int = 100) -> list[Record]:
    """Backward snowballing fallback via the Crossref ``reference`` list."""
    d = _norm_doi(doi)
    if not d:
        return []
    params = {"mailto": config.CONTACT_EMAIL}
    msg = (http_get(f"{CR_WORKS}/{d}", params).json() or {}).get("message", {}) or {}
    out: list[Record] = []
    for ref in (msg.get("reference") or [])[:retmax]:
        ref = ref or {}
        rdoi = _norm_doi(ref.get("DOI"))
        title = clean(ref.get("article-title") or ref.get("unstructured") or "")
        if not (rdoi or title):
            continue
        author = clean(ref.get("author", ""))
        year = None
        yr = clean(ref.get("year", ""))
        if yr[:4].isdigit():
            year = int(yr[:4])
        out.append(Record(
            source="snowball:backward",
            source_id=rdoi or clean(ref.get("key", "")),
            doi=rdoi,
            title=title,
            authors=[author] if author else [],
            year=year,
            journal=clean(ref.get("journal-title", "")),
            raw=ref,
        ))
    return out


# ── forward (cited-by) ───────────────────────────────────────────────────────
def cited_by_openalex(work_id_or_doi: str, *, retmax: int = 100) -> list[Record]:
    """Forward snowballing via the OpenAlex ``cites:`` filter."""
    raw = clean(work_id_or_doi)
    oa_id = _oa_id(raw) if _is_oa_id(raw) else _oa_id((_resolve_work(raw)).get("id"))
    if not oa_id:
        return []
    params = {
        "filter": f"cites:{oa_id}",
        "per-page": min(retmax, 200),
        "mailto": config.CONTACT_EMAIL,
    }
    data = http_get(OA_WORKS, params).json() or {}
    out = [_record_from_oa(w, "snowball:forward")
           for w in (data.get("results") or [])]
    return out[:retmax]


# ── orchestration ────────────────────────────────────────────────────────────
def _seed_handle(seed: Record) -> Optional[str]:
    """Pick the best citation handle for a seed: DOI, else an OpenAlex id."""
    if seed.doi:
        return _norm_doi(seed.doi)
    for cand in (seed.source_id, seed.url):
        if _is_oa_id(cand):
            return _oa_id(cand)
    return None


def snowball(seeds: list[Record], *, directions=("backward", "forward"),
             per_seed: int = 100, max_total: int = 200,
             backend: str = "openalex") -> list[Record]:
    """Chase citations from each seed, dedup against seeds, cap the total.

    Resilient: a failure in one direction for one seed never aborts the sweep.
    """
    seed_uids = {s.uid for s in seeds}
    seen: set[str] = set()
    out: list[Record] = []

    def _add(recs: list[Record]) -> bool:
        """Append new, non-seed, non-dup records. Returns False once full."""
        for r in recs:
            if len(out) >= max_total:
                return False
            uid = r.uid
            if uid in seed_uids or uid in seen:
                continue
            seen.add(uid)
            out.append(r)
        return len(out) < max_total

    for seed in seeds:
        if len(out) >= max_total:
            break
        handle = _seed_handle(seed)
        if not handle:               # nothing to chase from
            continue
        if "backward" in directions:
            try:
                if backend == "crossref":
                    recs = references_crossref(handle, retmax=per_seed)
                else:
                    recs = references_openalex(handle, retmax=per_seed)
                    if not recs and seed.doi:   # OpenAlex empty → Crossref fallback
                        recs = references_crossref(seed.doi, retmax=per_seed)
                _add(recs)
            except Exception:
                pass
        if "forward" in directions and len(out) < max_total:
            try:
                _add(cited_by_openalex(handle, retmax=per_seed))
            except Exception:
                pass
    return out[:max_total]
