"""Literature source clients (identification phase, PRISMA item 7–8)."""
from .fulltext import (FullText, FullTextRetriever, HttpFullTextRetriever,
                       McpFullTextRetriever)
from .registry import SOURCES, search_source, synthetic_records

__all__ = [
    "SOURCES", "search_source", "synthetic_records",
    "FullText", "FullTextRetriever", "HttpFullTextRetriever", "McpFullTextRetriever",
]
