"""Cross-source de-duplication (PRISMA item 16a).

Strategy: exact match on normalised DOI first, then fuzzy match on normalised
title (token-sort ratio) for records lacking a DOI. When duplicates collapse,
the most information-rich record (longest abstract, most authors) is retained.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from .models import Record

_TITLE_THRESHOLD = 92  # token_sort_ratio above which two titles are "the same"


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (t or "").lower()).strip()


def _richness(r: Record) -> int:
    return len(r.abstract or "") + 10 * len(r.authors)


def deduplicate(records: list[Record]) -> tuple[list[Record], int]:
    """Return (unique_records, n_duplicates_removed)."""
    by_doi: dict[str, Record] = {}
    no_doi: list[Record] = []

    for r in records:
        if r.doi:
            key = f"doi:{r.doi.lower().strip()}"
            if key not in by_doi or _richness(r) > _richness(by_doi[key]):
                by_doi[key] = r
        else:
            no_doi.append(r)

    unique = list(by_doi.values())

    # Fuzzy-match DOI-less records against the growing unique set.
    kept_titles: list[tuple[str, int]] = [
        (_norm_title(u.title), idx) for idx, u in enumerate(unique)
    ]
    for r in no_doi:
        nt = _norm_title(r.title)
        if not nt:
            unique.append(r)
            kept_titles.append((nt, len(unique) - 1))
            continue
        match_idx = None
        for title, idx in kept_titles:
            if title and fuzz.token_sort_ratio(nt, title) >= _TITLE_THRESHOLD:
                match_idx = idx
                break
        if match_idx is None:
            unique.append(r)
            kept_titles.append((nt, len(unique) - 1))
        elif _richness(r) > _richness(unique[match_idx]):
            unique[match_idx] = r

    removed = len(records) - len(unique)
    return unique, removed
