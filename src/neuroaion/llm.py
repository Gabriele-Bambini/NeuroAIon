"""LLM provider abstraction.

Three ways to drive the pipeline:

* ``AnthropicProvider`` / ``OpenAICompatibleProvider`` — direct API calls with an
  API key (fully autonomous, unattended).
* ``CoworkProvider`` — the pipeline delegates every LLM call to the *controlling
  agent* (e.g. Claude Code running on the user's monthly subscription): no API
  key, the orchestrating model IS the provider. A handler is injected via
  :func:`set_cowork_handler`; a content-addressed on-disk request/response queue
  is the batch fallback.
* ``MockProvider`` — deterministic schema-valid placeholders for **tests / CI
  only**. It never represents a real review and must be opted into explicitly.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

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


# ── OpenAI-compatible provider (DeepSeek V-series, OpenAI, Qwen, local...) ────
class OpenAICompatibleProvider(LLMProvider):
    """Any chat backend exposing the OpenAI ``/chat/completions`` schema.

    Structured output is obtained via JSON mode (``response_format`` =
    ``json_object``) plus the schema embedded in the prompt and Pydantic-free
    ``json.loads`` validation with one repair retry — these backends do not offer
    Anthropic's guaranteed json_schema enforcement. Designed for cheap, high-volume
    work such as title/abstract screening.
    """

    def __init__(self, *, base_url: str, api_key: str, model: str):
        import requests  # already a dependency

        self._requests = requests
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _post(self, messages: list[dict], *, max_tokens: int, json_mode: bool) -> str:
        url = f"{self.base_url}/chat/completions"
        body: dict[str, Any] = {
            "model": self.model, "messages": messages, "max_tokens": max_tokens,
            "temperature": 0,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        resp = self._requests.post(url, json=body, headers=headers, timeout=180)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    @retry(reraise=True, stop=stop_after_attempt(5),
           wait=wait_exponential(multiplier=2, min=2, max=30))
    def complete_json(self, *, system, user, schema, cache_prefix=None, max_tokens=8000):
        sys_text = (cache_prefix + "\n\n" + system) if cache_prefix else system
        sys_text += ("\n\nReturn ONLY a single JSON object that conforms to this "
                     "JSON Schema (no prose, no markdown fences):\n" + json.dumps(schema))
        messages = [{"role": "system", "content": sys_text},
                    {"role": "user", "content": user}]
        text = self._post(messages, max_tokens=max_tokens, json_mode=True)
        return _parse_json_lenient(text)

    @retry(reraise=True, stop=stop_after_attempt(5),
           wait=wait_exponential(multiplier=2, min=2, max=30))
    def complete_text(self, *, system, user, cache_prefix=None, max_tokens=16000):
        sys_text = (cache_prefix + "\n\n" + system) if cache_prefix else system
        messages = [{"role": "system", "content": sys_text},
                    {"role": "user", "content": user}]
        return self._post(messages, max_tokens=max_tokens, json_mode=False)


def _parse_json_lenient(text: str) -> dict[str, Any]:
    """Parse a JSON object that may be wrapped in markdown fences or stray prose."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


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
            "## Mock narrative (NOT a real review)\n\n"
            "Deterministic placeholder from MockProvider — for tests/CI only. Set "
            "ANTHROPIC_API_KEY (or a DeepSeek/OpenAI key) for an API-driven run, or "
            "drive the pipeline from an agent on your subscription (cowork mode).\n"
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


# ── Cowork provider (agent-driven; the controlling model IS the provider) ─────
#
# When a user tells an agent ("Claude Code, run this pipeline with my monthly
# subscription"), there is no API key — the orchestrating model answers every
# LLM call itself. The agent binds a handler once with ``set_cowork_handler``;
# the pipeline then runs unchanged. Without a handler, requests are queued to
# disk (content-addressed) so they can be answered in a batch and the run
# resumed (answered calls are cached and returned on the next pass).

_COWORK_HANDLER: Optional[Callable[..., Any]] = None


def set_cowork_handler(fn: Optional[Callable[..., Any]]) -> None:
    """Bind the callable that fulfils LLM calls in cowork mode.

    ``fn(kind, system, user, schema, cache_prefix, max_tokens)`` must return a
    ``dict`` when ``kind == 'json'`` (matching ``schema``) or a ``str`` when
    ``kind == 'text'``.
    """
    global _COWORK_HANDLER
    _COWORK_HANDLER = fn


def cowork_ready() -> bool:
    """True if cowork can serve calls: a handler is bound or a response dir exists."""
    return _COWORK_HANDLER is not None or bool(config.COWORK_DIR)


class CoworkPending(RuntimeError):
    """Raised when a cowork request has no answer yet (batch/disk mode)."""


class CoworkProvider(LLMProvider):
    def __init__(self, handler: Optional[Callable[..., Any]] = None,
                 response_dir: str | None = None, model: str = "cowork"):
        self.handler = handler if handler is not None else _COWORK_HANDLER
        self.dir = response_dir or config.COWORK_DIR or ".neuroaion_cowork"
        self.model = model

    @staticmethod
    def _key(kind: str, system: str, user: str) -> str:
        return hashlib.sha1(f"{kind}\x00{system}\x00{user}".encode("utf-8")).hexdigest()[:20]

    def _serve(self, kind, *, system, user, schema, cache_prefix, max_tokens):
        if self.handler is not None:
            return self.handler(kind=kind, system=system, user=user, schema=schema,
                                cache_prefix=cache_prefix, max_tokens=max_tokens)
        # Disk batch fallback: return a cached answer or queue the request.
        key = self._key(kind, system, user)
        rdir = os.path.join(self.dir, "responses")
        qdir = os.path.join(self.dir, "requests")
        os.makedirs(rdir, exist_ok=True)
        os.makedirs(qdir, exist_ok=True)
        ext = "json" if kind == "json" else "txt"
        rpath = os.path.join(rdir, f"{key}.{ext}")
        if os.path.exists(rpath):
            raw = open(rpath, encoding="utf-8").read()
            return _parse_json_lenient(raw) if kind == "json" else raw
        with open(os.path.join(qdir, f"{key}.json"), "w", encoding="utf-8") as fh:
            json.dump({"kind": kind, "system": system, "user": user,
                       "schema": schema, "max_tokens": max_tokens}, fh, indent=2)
        raise CoworkPending(
            f"Cowork request {key} needs an answer. Write {rpath} then re-run to "
            f"resume (answered calls are cached). Bind set_cowork_handler(...) to "
            f"answer live.")

    def complete_json(self, *, system, user, schema, cache_prefix=None, max_tokens=8000):
        out = self._serve("json", system=system, user=user, schema=schema,
                          cache_prefix=cache_prefix, max_tokens=max_tokens)
        return out if isinstance(out, dict) else _parse_json_lenient(str(out))

    def complete_text(self, *, system, user, cache_prefix=None, max_tokens=16000):
        out = self._serve("text", system=system, user=user, schema=None,
                          cache_prefix=cache_prefix, max_tokens=max_tokens)
        return out if isinstance(out, str) else json.dumps(out)


# ── Provider selection ────────────────────────────────────────────────────────
def provider_ready() -> bool:
    """True if a real (non-mock) provider can run: an API key OR cowork is bound.

    This is the fail-closed predicate — the engine must not silently fabricate a
    review with MockProvider unless mock is explicitly requested.
    """
    if config.PROVIDER == "cowork":
        return cowork_ready()
    return config.have_api_key() or cowork_ready()


def build_provider(name: str, model: str | None = None) -> LLMProvider:
    """Construct a provider by name: anthropic | cowork | deepseek | openai | custom | mock."""
    if name == "mock":
        return MockProvider()
    if name == "cowork":
        return CoworkProvider(model=model or "cowork")
    if name == "anthropic":
        return AnthropicProvider(model=model)
    base, keyenv, default_model = config.OPENAI_COMPATIBLE.get(
        name, config.OPENAI_COMPATIBLE["custom"])
    api_key = os.environ.get(keyenv, "").strip()
    if not base or not api_key:
        return MockProvider()
    return OpenAICompatibleProvider(base_url=base, api_key=api_key,
                                    model=model or default_model)


def get_provider(mock: bool, model: str | None = None) -> LLMProvider:
    """Default provider for the run, honouring NEUROAION_PROVIDER and cowork.

    Priority: explicit mock → cowork (if selected or a handler is bound) →
    the configured API provider.
    """
    if mock:
        return MockProvider()
    if config.PROVIDER == "cowork" or (_COWORK_HANDLER is not None and not config.have_api_key()):
        return CoworkProvider(model=model or "cowork")
    return build_provider(config.PROVIDER, model or config.DEFAULT_MODEL)
