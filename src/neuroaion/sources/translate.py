"""Per-database query translation (PRISMA item 7 — reproducible search syntax).

Turns the protocol's concept groups (OR within a group, AND across groups) into
the native Boolean syntax of each database, so the recorded search strategy is
faithful and re-runnable by a librarian. Deterministic — it works offline and in
mock runs, and also serves as a scaffold the SearchStrategist LLM can refine.

Field conventions implemented:
  * PubMed         — ``"term"[tiab]`` / ``"term"[MeSH Terms]`` + ``("y1"[dp] : "y2"[dp])``
  * Europe PMC     — ``(TITLE:"t" OR ABSTRACT:"t")`` + ``PUB_YEAR:[y1 TO y2]``
  * Scopus         — ``TITLE-ABS-KEY("t" OR "u")`` + ``PUBYEAR > / <``
  * Web of Science — ``TS=("t" OR "u")`` (Topic) + ``PY=(y1-y2)``
  * arXiv          — ``(abs:"t" OR abs:"u")`` with AND/OR
  * IEEE Xplore    — ``("Abstract":t OR ...)``
  * default/plain  — quoted Boolean (OpenAlex, Crossref, S2, CORE, DOAJ, bioRxiv)
"""
from __future__ import annotations

import re
from typing import Optional

KEYWORD_GROUPS = list  # alias for readability: list[list[str]]


def _year(value: Optional[str]) -> Optional[str]:
    if not value or str(value).lower() == "auto":
        return None
    m = re.search(r"(19|20)\d{2}", str(value))
    return m.group(0) if m else None


def _q(term: str) -> str:
    """Quote a multiword term; leave single tokens bare."""
    t = term.strip()
    return f'"{t}"' if " " in t else t


def _plain(groups, *, quote_all=False) -> str:
    parts = []
    for g in groups:
        if not g:
            continue
        terms = [f'"{t.strip()}"' if (quote_all or " " in t) else t.strip() for t in g]
        parts.append("(" + " OR ".join(terms) + ")")
    return " AND ".join(parts)


# ── PubMed ───────────────────────────────────────────────────────────────────
def _pubmed(groups, df, dt) -> str:
    parts = []
    for g in groups:
        if not g:
            continue
        terms = [f'{_q(t)}[Title/Abstract]' for t in g]
        parts.append("(" + " OR ".join(terms) + ")")
    q = " AND ".join(parts)
    y1, y2 = _year(df), _year(dt)
    if y1 or y2:
        q = f'{q} AND ("{y1 or "1800"}"[Date - Publication] : "{y2 or "3000"}"[Date - Publication])'
    return q


# ── Europe PMC ───────────────────────────────────────────────────────────────
def _europepmc(groups, df, dt) -> str:
    parts = []
    for g in groups:
        if not g:
            continue
        terms = [f'(TITLE:{_q(t)} OR ABSTRACT:{_q(t)})' for t in g]
        parts.append("(" + " OR ".join(terms) + ")")
    q = " AND ".join(parts)
    y1, y2 = _year(df), _year(dt)
    if y1 or y2:
        q = f'{q} AND (PUB_YEAR:[{y1 or "1800"} TO {y2 or "3000"}])'
    return q


# ── Scopus (RIS/CSV export search box) ───────────────────────────────────────
def _scopus(groups, df, dt) -> str:
    parts = []
    for g in groups:
        if not g:
            continue
        inner = " OR ".join(_q(t) for t in g)
        parts.append(f"TITLE-ABS-KEY({inner})")
    q = " AND ".join(parts)
    y1, y2 = _year(df), _year(dt)
    if y1:
        q += f" AND PUBYEAR > {int(y1) - 1}"
    if y2:
        q += f" AND PUBYEAR < {int(y2) + 1}"
    return q


# ── Web of Science (advanced search) ─────────────────────────────────────────
def _wos(groups, df, dt) -> str:
    parts = []
    for g in groups:
        if not g:
            continue
        inner = " OR ".join(_q(t) for t in g)
        parts.append(f"TS=({inner})")
    q = " AND ".join(parts)
    y1, y2 = _year(df), _year(dt)
    if y1 or y2:
        q += f" AND PY=({y1 or '1800'}-{y2 or '3000'})"
    return q


# ── arXiv (Atom query API) ───────────────────────────────────────────────────
def _arxiv(groups, df, dt) -> str:
    parts = []
    for g in groups:
        if not g:
            continue
        terms = [f'abs:{_q(t)}' for t in g]
        parts.append("(" + " OR ".join(terms) + ")")
    return " AND ".join(parts)


# ── IEEE Xplore ──────────────────────────────────────────────────────────────
def _ieee(groups, df, dt) -> str:
    parts = []
    for g in groups:
        if not g:
            continue
        terms = [f'"Abstract":{_q(t)}' for t in g]
        parts.append("(" + " OR ".join(terms) + ")")
    return " AND ".join(parts)


_TRANSLATORS = {
    "pubmed": _pubmed,
    "europepmc": _europepmc,
    "scopus": _scopus,
    "wos": _wos,
    "webofscience": _wos,
    "arxiv": _arxiv,
    "ieee": _ieee,
    "ieeexplore": _ieee,
}


def translate(source: str, keywords, date_from=None, date_to=None) -> str:
    """Return the native Boolean query for *source* from concept groups.

    Unknown / plain databases (OpenAlex, Crossref, Semantic Scholar, CORE, DOAJ,
    bioRxiv, ClinicalTrials) get a quoted Boolean that every engine accepts.
    """
    if not keywords:
        return ""
    fn = _TRANSLATORS.get((source or "").strip().lower())
    if fn is not None:
        return fn(keywords, date_from, date_to)
    # ClinicalTrials.gov prefers unquoted concept ORs; everything else: quoted Boolean.
    return _plain(keywords, quote_all=(source or "").lower() not in {"clinicaltrials"})


def supported() -> list[str]:
    return sorted(_TRANSLATORS)
