"""Base class shared by every agent."""
from __future__ import annotations

from typing import Any, Optional

from ..llm import LLMProvider
from ..models import ReviewProtocol


class Agent:
    """An agent bundles a role, a system prompt, and an LLM provider.

    The protocol's eligibility contract is supplied as a cache prefix so the
    large shared context is billed once and re-read cheaply across the many
    per-record calls made during screening and extraction.
    """

    name: str = "Agent"
    role: str = ""

    def __init__(self, provider: LLMProvider, protocol: ReviewProtocol):
        self.provider = provider
        self.protocol = protocol

    @property
    def cache_prefix(self) -> str:
        return (
            "You are part of NeuroAIon, an automated systematic-review system that "
            "rigorously follows PRISMA 2020. Apply the review protocol below exactly. "
            "Be conservative, evidence-bound, and never fabricate data.\n\n"
            "=== REVIEW PROTOCOL ===\n" + self.protocol.criteria_block()
        )

    def ask_json(self, system: str, user: str, schema: dict[str, Any],
                 max_tokens: int = 8000) -> dict[str, Any]:
        return self.provider.complete_json(
            system=system, user=user, schema=schema,
            cache_prefix=self.cache_prefix, max_tokens=max_tokens,
        )

    def ask_text(self, system: str, user: str, max_tokens: int = 16000,
                 cache_prefix: Optional[str] = None) -> str:
        return self.provider.complete_text(
            system=system, user=user,
            cache_prefix=cache_prefix if cache_prefix is not None else self.cache_prefix,
            max_tokens=max_tokens,
        )


def obj(properties: dict[str, Any], required: Optional[list[str]] = None) -> dict[str, Any]:
    """Helper to build a strict JSON-schema object."""
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties.keys()),
        "additionalProperties": False,
    }
