"""Cross-source de-duplication (PRISMA item 16a).

Identifier-aware union-find: two records are the same study if they share *any*
unique identifier (DOI / PMID / PMCID / arXiv / OpenAlex / S2 / …) or, lacking a
shared id, a near-identical title. When a cluster collapses, the richest record
survives and **all** identifiers, provenance (``found_by``) and the best
non-empty value of every bibliographic field are merged onto it — nothing is
lost, so citations stay complete and verifiable.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from .models import Record

_TITLE_THRESHOLD = 92  # token_sort_ratio above which two titles are "the same"


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (t or "").lower()).strip()


def _richness(r: Record) -> int:
    return len(r.abstract or "") + 10 * len(r.authors) + 3 * len(r.all_ids())


class _UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def _merge_into(base: Record, other: Record) -> None:
    """Union identifiers, provenance and best-available metadata onto *base*."""
    merged = dict(other.all_ids())
    merged.update(base.all_ids())          # base wins on conflicts
    base.ids = merged
    if not base.doi and other.doi:
        base.doi = other.doi
    if not base.pmid and other.pmid:
        base.pmid = other.pmid
    base.found_by = sorted(set((base.found_by or [base.source]) +
                               (other.found_by or [other.source])))
    for field in ("abstract", "journal", "journal_abbrev", "volume", "issue",
                  "pages", "url", "retrieval_date"):
        if not getattr(base, field, "") and getattr(other, field, ""):
            setattr(base, field, getattr(other, field))
    if len(other.authors) > len(base.authors):
        base.authors = other.authors
    if base.year is None and other.year is not None:
        base.year = other.year


def deduplicate(records: list[Record]) -> tuple[list[Record], int]:
    """Return (unique_records, n_duplicates_removed)."""
    n = len(records)
    if n == 0:
        return [], 0
    uf = _UF(n)

    # 1) Union any two records that share an identifier.
    id_owner: dict[str, int] = {}
    for i, r in enumerate(records):
        for key in r.id_keys():
            if key in id_owner:
                uf.union(i, id_owner[key])
            else:
                id_owner[key] = i

    # 2) Union DOI/id-less records to an existing one by fuzzy title.
    titled: list[tuple[str, int]] = []
    for i, r in enumerate(records):
        nt = _norm_title(r.title)
        if not nt:
            continue
        if not r.id_keys():                # only fuzzy-merge when it has no id
            match = next((j for t, j in titled
                          if fuzz.token_sort_ratio(nt, t) >= _TITLE_THRESHOLD), None)
            if match is not None:
                uf.union(i, match)
        titled.append((nt, i))

    # 3) Collapse clusters: richest survives, merge everything onto it.
    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(uf.find(i), []).append(i)

    unique: list[Record] = []
    for members in clusters.values():
        members.sort(key=lambda i: _richness(records[i]), reverse=True)
        base = records[members[0]].model_copy(deep=True)
        if not base.found_by:
            base.found_by = [base.source]
        for j in members[1:]:
            _merge_into(base, records[j])
        unique.append(base)

    return unique, n - len(unique)
