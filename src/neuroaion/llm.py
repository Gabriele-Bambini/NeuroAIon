"""LLM provider abstraction.

`AnthropicProvider` drives Claude Opus 4.8 with adaptive thinking, structured
JSON outputs (``output_config.format``), prompt caching of the stable protocol
context, and automatic retry. `MockProvider` synthesises schema-conforming
responses deterministically so the entire pipeline can run full-auto with no
API key — for testing, demos, and CI.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from abc import ABC, abstractmethod
from typing import Any, Optional

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from . import config


class LLMProvider(ABC):
    """Common interface every agent talks to."""

    @abstractmethod
    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        cache_prefix: Optional[str] = None,
        max_tokens: int = 8000,
    ) -> dict[str, Any]:
        """Return a dict guaranteed to match ``schema``."""

    @abstractmethod
    def complete_text(
        self,
        *,
        system: str,
        user: str,
        cache_prefix: Optional[str] = None,
        max_tokens: int = 16000,
    ) -> str:
        """Return free-form text (used by the report writer)."""


# ── Live provider ────────────────────────────────────────────────────────────
class AnthropicProvider(LLMProvider):
    def __init__(self, model: str | None = None):
        import anthropic  # imported lazily so mock runs need no SDK installed

        self._anthropic = anthropic
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
        self.model = model or config.DEFAULT_MODEL

    def _system_blocks(self, system: str, cache_prefix: Optional[str]) -> list[dict]:
        """Place the stable protocol prefix first with a cache breakpoint, so the
        large shared context is billed once and re-read across hundreds of
        per-record screening/extraction calls."""
        blocks: list[dict] = []
        if cache_prefix:
            blocks.append(
                {"type": "text", "text": cache_prefix, "cache_control": {"type": "ephemeral"}}
            )
            blocks.append({"type": "text", "text": system})
        else:
            blocks.append({"type": "text", "text": system, "cache_control": {"type": "ephemeral"}})
        return blocks

    @retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(Exception),
    )
    def complete_json(self, *, system, user, schema, cache_prefix=None, max_tokens=8000):
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": schema}},
            system=self._system_blocks(system, cache_prefix),
            messages=[{"role": "user", "content": user}],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return json.loads(text)

    @retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(Exception),
    )
    def complete_text(self, *, system, user, cache_prefix=None, max_tokens=16000):
        # Stream for long outputs to avoid HTTP timeouts; collect the final message.
        with self.client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=self._system_blocks(system, cache_prefix),
            messages=[{"role": "user", "content": user}],
        ) as stream:
            final = stream.get_final_message()
        return "".join(b.text for b in final.content if b.type == "text")


# ── Deterministic mock provider ──────────────────────────────────────────────
class MockProvider(LLMProvider):
    """Generates schema-valid placeholder content without any network call.

    Decisions are deterministic functions of the input so that runs are
    reproducible and PRISMA counts come out stable. This lets the entire
    full-auto pipeline be exercised offline.
    """

    def __init__(self, model: str = "mock"):
        self.model = model

    @staticmethod
    def _seed(text: str) -> random.Random:
        h = int(hashlib.sha1(text.encode("utf-8")).hexdigest(), 16)
        return random.Random(h)

    def complete_json(self, *, system, user, schema, cache_prefix=None, max_tokens=8000):
        rng = self._seed(system + user)
        return _sample_schema(schema, rng, context=user)

    def complete_text(self, *, system, user, cache_prefix=None, max_tokens=16000):
        return (
            "## Mock narrative\n\n"
            "This text was produced by NeuroAIon's deterministic MockProvider "
            "(no Anthropic API key configured). It demonstrates the end-to-end "
            "pipeline. Set ANTHROPIC_API_KEY for a real, model-authored review.\n"
        )


def _sample_schema(schema: dict[str, Any], rng: random.Random, context: str = "") -> Any:
    """Recursively synthesise a value matching a (subset of) JSON Schema."""
    if "enum" in schema:
        return _pick_enum(schema["enum"], rng, context)

    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), t[0])

    if t == "object":
        props = schema.get("properties", {})
        required = set(schema.get("required", props.keys()))
        return {
            name: _sample_schema(sub, rng, context)
            for name, sub in props.items()
            if name in required
        }
    if t == "array":
        item = schema.get("items", {"type": "string"})
        n = 1
        return [_sample_schema(item, rng, context) for _ in range(n)]
    if t == "integer":
        return rng.randint(10, 120)
    if t == "number":
        return round(rng.uniform(-1.0, 1.0), 3)
    if t == "boolean":
        return rng.random() > 0.4
    # string
    return _sample_string(schema, rng, context)


def _pick_enum(values: list, rng: random.Random, context: str):
    # Bias screening decisions so a realistic fraction survives each stage.
    lowered = [str(v).lower() for v in values]
    if "include" in lowered and "exclude" in lowered:
        r = rng.random()
        if r < 0.30:
            return values[lowered.index("include")]
        if r < 0.45 and "maybe" in lowered:
            return values[lowered.index("maybe")]
        return values[lowered.index("exclude")]
    if {"low", "high"} & set(lowered):
        return rng.choice(values)
    return values[0]


def _sample_string(schema: dict, rng: random.Random, context: str) -> str:
    title = _extract_record_title(context)
    return f"[mock] {title}" if title else "[mock]"


def _extract_record_title(context: str) -> str:
    m = re.search(r"TITLE:\s*(.+)", context)
    if m:
        return m.group(1).strip()[:80]
    return ""


def get_provider(mock: bool, model: str | None = None) -> LLMProvider:
    if mock or not config.have_api_key():
        return MockProvider()
    return AnthropicProvider(model=model)
