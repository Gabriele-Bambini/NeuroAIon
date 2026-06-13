"""Agent 3 — DeduplicationAgent (PRISMA item 16a).

De-duplication is a deterministic operation, so this agent delegates to the
``neuroaion.dedup`` engine rather than the language model — duplicate detection
must be exact and reproducible, not a matter of judgement.
"""
from __future__ import annotations

from ..dedup import deduplicate
from ..models import Record
from .base import Agent


class DeduplicationAgent(Agent):
    name = "DeduplicationAgent"
    role = "Remove duplicate records across sources before screening."

    def run(self, records: list[Record]) -> tuple[list[Record], int]:
        return deduplicate(records)
