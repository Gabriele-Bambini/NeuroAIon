"""Source registry + dispatch, and a synthetic generator for offline runs."""
from __future__ import annotations

import hashlib
import random
from typing import Callable

from ..models import Record
from . import biorxiv, crossref, europepmc, openalex, pubmed

SOURCES: dict[str, Callable[..., list[Record]]] = {
    "pubmed": pubmed.search,
    "europepmc": europepmc.search,
    "crossref": crossref.search,
    "openalex": openalex.search,
    "biorxiv": biorxiv.search,
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
_ADJ = ["modulates", "enhances", "fails to alter", "improves", "has no effect on"]
_TOPIC = ["working memory", "n-back accuracy", "executive function",
          "cognitive control", "attention"]
_DESIGN = ["double-blind randomized controlled trial", "randomized crossover trial",
           "single-blind RCT", "narrative review", "animal study"]


def synthetic_records(source: str, query: str, n: int, seed_offset: int = 0) -> list[Record]:
    """Produce `n` plausible-but-fake records, deterministic from (source, query)."""
    rng = random.Random(
        int(hashlib.sha1(f"{source}:{query}:{seed_offset}".encode()).hexdigest(), 16)
    )
    out: list[Record] = []
    for i in range(n):
        design = rng.choice(_DESIGN)
        topic = rng.choice(_TOPIC)
        verb = rng.choice(_ADJ)
        year = rng.randint(2011, 2024)
        first = rng.choice(["Rossi", "Smith", "Nakamura", "Müller", "Dubois", "Khan", "Silva"])
        # 1-in-7 records share a DOI with a neighbour to exercise deduplication.
        shared = i > 0 and rng.random() < 0.14
        doi = f"10.1234/neuroaion.{(i - 1) if shared else i:04d}"
        out.append(Record(
            source=source,
            source_id=f"{source}-{i:04d}",
            doi=doi,
            title=f"Anodal tDCS {verb} {topic}: a {design}",
            abstract=(f"Background: We tested whether anodal tDCS over DLPFC {verb} {topic} "
                      f"in healthy adults. Methods: {design} with sham control "
                      f"(n={rng.randint(16, 80)}). Results: effect size {rng.uniform(-0.3,0.9):.2f}."),
            authors=[f"{first} {chr(65+i%26)}", "Bianchi L"],
            year=year,
            journal=rng.choice(["NeuroImage", "Brain Stimul", "J Cogn Neurosci", "bioRxiv"]),
            url=f"https://doi.org/{doi}",
        ))
    return out
