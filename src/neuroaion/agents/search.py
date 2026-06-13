"""Agent 2 — SearchStrategist (PRISMA items 7–8)."""
from __future__ import annotations

from ..models import DatabaseQuery, SearchStrategy
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
        base = _boolean_from_keywords(keywords)

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
            f"Date range: {self.protocol.search.date_from} to {self.protocol.search.date_to}.\n"
            "For PubMed use MeSH where helpful; for the others use plain Boolean. "
            "Return one query per database. Keep them faithful to the eligibility criteria."
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
                        source=src, query=q.get("query") or base,
                        rationale=q.get("rationale", ""),
                    ))
            strategy.notes = out.get("notes", "")
        except Exception:  # noqa: BLE001
            pass

        # Guarantee every configured source has a query.
        covered = {q.source for q in strategy.queries}
        for src in sources:
            if src not in covered:
                strategy.queries.append(DatabaseQuery(
                    source=src, query=base,
                    rationale="Auto-generated Boolean from protocol keywords.",
                ))
        return strategy
