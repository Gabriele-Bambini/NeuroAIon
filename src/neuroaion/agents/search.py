"""Agent 2 — SearchStrategist (PRISMA items 7–8)."""
from __future__ import annotations

from ..models import DatabaseQuery, SearchStrategy
from ..sources import translate as _translate
from .base import Agent, obj


def _boolean_from_keywords(keywords: list[list[str]]) -> str:
    """Fallback Boolean: OR within a concept group, AND across groups."""
    groups = []
    for group in keywords:
        terms = " OR ".join(f'"{t}"' if " " in t else t for t in group)
        groups.append(f"({terms})")
    return " AND ".join(groups) if groups else ""


class SearchStrategist(Agent):
    name = "SearchStrategist"
    role = "Translate the protocol into database-specific search strategies."

    def design(self) -> SearchStrategy:
        sources = self.protocol.search.sources
        keywords = self.protocol.search.keywords
        df, dt = self.protocol.search.date_from, self.protocol.search.date_to
        base = _boolean_from_keywords(keywords)
        # Deterministic native-syntax query per database (PubMed [tiab]/MeSH dates,
        # Europe PMC TITLE/ABSTRACT, Scopus TITLE-ABS-KEY, WoS TS=, arXiv abs:, …).
        native = {src: (_translate.translate(src, keywords, df, dt) or base) for src in sources}
        scaffold = "\n".join(f"  {s}: {q}" for s, q in native.items())

        # Ask the model for tailored per-database syntax; fall back to the base query.
        schema = obj({
            "queries": {
                "type": "array",
                "items": obj({
                    "source": {"type": "string"},
                    "query": {"type": "string"},
                    "rationale": {"type": "string"},
                }),
            },
            "notes": {"type": "string"},
        })
        user = (
            f"Design search strategies for these databases: {', '.join(sources)}.\n"
            f"Concept groups (OR within, AND across):\n{keywords}\n"
            f"Date range: {df} to {dt}.\n"
            "A deterministic native-syntax draft per database is provided below; "
            "refine each (add MeSH/Emtree terms, synonyms, truncation, field tags) "
            "without broadening beyond the eligibility criteria:\n"
            f"{scaffold}\n"
            "Return one query per database, faithful to the eligibility criteria."
        )
        strategy = SearchStrategy()
        try:
            out = self.ask_json(
                "You are an expert biomedical information specialist (librarian).",
                user, schema, max_tokens=3000,
            )
            for q in out.get("queries", []):
                src = q.get("source", "").lower()
                if src in sources:
                    strategy.queries.append(DatabaseQuery(
                        source=src, query=q.get("query") or native.get(src) or base,
                        rationale=q.get("rationale", ""),
                    ))
            strategy.notes = out.get("notes", "")
        except Exception:  # noqa: BLE001
            pass

        # Guarantee every configured source has a query (native syntax fallback).
        covered = {q.source for q in strategy.queries}
        for src in sources:
            if src not in covered:
                strategy.queries.append(DatabaseQuery(
                    source=src, query=native.get(src) or base,
                    rationale="Deterministic native-syntax query from protocol concept groups.",
                ))
        return strategy
