"""Source registry + dispatch, and a synthetic generator for offline runs."""
from __future__ import annotations

import hashlib
import random
from typing import Callable

from ..models import Record
from . import (arxiv, biorxiv, clinicaltrials, crossref, doaj, europepmc,
               openalex, pubmed, semanticscholar)

SOURCES: dict[str, Callable[..., list[Record]]] = {
    "pubmed": pubmed.search,
    "europepmc": europepmc.search,
    "crossref": crossref.search,
    "openalex": openalex.search,
    "biorxiv": biorxiv.search,
    "clinicaltrials": clinicaltrials.search,
    "doaj": doaj.search,
    "semanticscholar": semanticscholar.search,
    "arxiv": arxiv.search,
}


def search_source(name: str, query: str, retmax: int = 200) -> list[Record]:
    """Run one source query, returning [] on any failure (the search must not
    abort the whole review because one database is unreachable)."""
    fn = SOURCES.get(name)
    if fn is None:
        return []
    try:
        return fn(query, retmax=retmax)
    except Exception:  # noqa: BLE001 — resilience is the point here
        return []


# ── Synthetic corpus for hermetic, offline, deterministic runs ───────────────
_DESIGNS = ["benchmark study", "comparative evaluation", "method-development paper",
            "empirical study", "ablation study", "systematic comparison", "review"]


def _terms_from_query(query: str) -> list[str]:
    """Extract candidate concept phrases from a Boolean query for synthetic titles."""
    import re
    phrases = re.findall(r'"([^"]+)"', query)          # quoted phrases
    rest = re.sub(r'"[^"]+"', " ", query)
    rest = re.sub(r'\b(AND|OR|NOT)\b', " ", rest)
    words = re.findall(r'[A-Za-z][A-Za-z0-9\-]{2,}', rest)
    seen, out = set(), []
    for t in phrases + words:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out or ["the method", "the task"]


def synthetic_records(source: str, query: str, n: int, seed_offset: int = 0) -> list[Record]:
    """Produce `n` plausible-but-fake records reflecting the query's topic,
    deterministic from (source, query). Used for offline/mock runs."""
    rng = random.Random(
        int(hashlib.sha1(f"{source}:{query}:{seed_offset}".encode()).hexdigest(), 16)
    )
    terms = _terms_from_query(query)
    methods = terms[: max(1, len(terms) // 2)] or terms
    tasks = terms[max(1, len(terms) // 2):] or terms
    out: list[Record] = []
    for i in range(n):
        method = rng.choice(methods)
        task = rng.choice(tasks)
        design = rng.choice(_DESIGNS)
        year = rng.randint(2017, 2024)
        first = rng.choice(["Zhang", "Smith", "Nguyen", "Müller", "Rossi", "Kumar", "Silva", "Chen"])
        shared = i > 0 and rng.random() < 0.14   # ~1/7 share a DOI to exercise dedup
        doi = f"10.1234/neuroaion.{(i - 1) if shared else i:04d}"
        out.append(Record(
            source=source, source_id=f"{source}-{i:04d}", doi=doi,
            title=f"{method} for {task}: a {design}",
            abstract=(f"We evaluate {method} on {task}. Methods: {design} against baselines "
                      f"(metric AUROC {rng.uniform(0.6,0.9):.2f}, AUPRC {rng.uniform(0.2,0.6):.2f}; "
                      f"n={rng.randint(3,12)} datasets). Effect size {rng.uniform(-0.2,0.9):.2f}."),
            authors=[f"{first} {chr(65+i%26)}", "Bianchi L"], year=year,
            journal=rng.choice(["Bioinformatics", "NeurIPS", "ICLR", "Nat Methods", "arXiv"]),
            url=f"https://doi.org/{doi}",
        ))
    return out
