"""Model-tier routing — right model for each task, on any coding agent.

The pipeline never pins a *version*; it pins a **capability tier** per stage:

* ``FLAGSHIP`` — hardest reasoning / writing / correctness-critical
  (PICO scoping, data extraction, evidence synthesis, manuscript, critic).
* ``STANDARD`` — judgement over full text, structured work
  (search-strategy refinement, full-text eligibility, risk-of-bias, claims).
* ``LIGHT``   — high-volume, simple classification (title/abstract screening,
  dedup tie-breaks).

Each provider family (Claude, OpenAI/Codex, Gemini/Antigravity, DeepSeek) maps a
tier to a concrete model **dynamically**: an env override wins, else the newest
model matching the tier's name pattern from a supplied ``available`` list, else a
sensible current default. So when e.g. Opus 4.9 ships, the flagship tier resolves
to it automatically — no code change. In cowork mode the tier is passed to the
controlling agent, which uses *its* flagship / standard / light model.
"""
from __future__ import annotations

import os
import re
from enum import Enum


class Tier(str, Enum):
    FLAGSHIP = "flagship"
    STANDARD = "standard"
    LIGHT = "light"


# Pipeline stage -> capability tier. Stage keys match the agents/steps.
STAGE_TIER: dict[str, Tier] = {
    "scoping": Tier.FLAGSHIP,          # scan literature, refine the PICO
    "protocol": Tier.FLAGSHIP,        # formalise/refine question + eligibility
    "search_strategy": Tier.STANDARD,  # MeSH/Emtree Boolean refinement
    "dedup": Tier.LIGHT,               # fuzzy-title tie-breaks
    "screen_ta": Tier.LIGHT,           # high-volume title/abstract screening
    "adjudication": Tier.STANDARD,     # resolve screening conflicts
    "eligibility": Tier.STANDARD,      # read full text, in/exclude
    "extraction": Tier.FLAGSHIP,       # pull/verify numbers from tables (critical)
    "rob": Tier.STANDARD,              # risk-of-bias signalling from full text
    "synthesis": Tier.FLAGSHIP,        # narrative + GRADE reasoning
    "claims": Tier.STANDARD,           # knowledge-graph claim extraction
    "reporter": Tier.FLAGSHIP,         # chaptered, grounded manuscript
    "critic": Tier.FLAGSHIP,           # self-critique / refinement
}


def tier_for(stage: str) -> Tier:
    return STAGE_TIER.get(stage, Tier.STANDARD)


# Provider-family aliases (agent identity or provider name -> canonical family).
_FAMILY_ALIASES = {
    "claude": "claude", "anthropic": "claude", "claude-code": "claude", "claudecode": "claude",
    "openai": "openai", "codex": "openai", "gpt": "openai", "chatgpt": "openai",
    "gemini": "gemini", "antigravity": "gemini", "google": "gemini",
    "deepseek": "deepseek",
}


def normalize_family(name: str) -> str:
    n = (name or "").strip().lower()
    if n in _FAMILY_ALIASES:
        return _FAMILY_ALIASES[n]
    for key, fam in _FAMILY_ALIASES.items():
        if key in n:
            return fam
    return "claude"


# Per-family, per-tier: a name pattern used to pick the *latest* matching model
# from a live model list, plus a current default (bump-able, and env-overridable).
# Defaults are examples that AUTO-UPGRADE: env override > latest-matching > default.
FAMILY_MODELS: dict[str, dict[Tier, dict]] = {
    "claude": {
        Tier.FLAGSHIP: {"pattern": r"claude-opus", "default": "claude-opus-4-8"},
        Tier.STANDARD: {"pattern": r"claude-sonnet", "default": "claude-sonnet-5"},
        Tier.LIGHT:    {"pattern": r"claude-haiku", "default": "claude-haiku-4-5"},
    },
    "openai": {
        Tier.FLAGSHIP: {"pattern": r"^(gpt-5(\.\d+)?|o[34])(?!.*(mini|nano))", "default": "gpt-5.1"},
        Tier.STANDARD: {"pattern": r"(gpt-5.*mini|gpt-4\.1(?!-mini))", "default": "gpt-5.1-mini"},
        Tier.LIGHT:    {"pattern": r"(gpt-5.*nano|gpt-4\.1-mini|gpt-4o-mini)", "default": "gpt-5.1-nano"},
    },
    "gemini": {
        Tier.FLAGSHIP: {"pattern": r"gemini-[\d.]+-?pro", "default": "gemini-3-pro"},
        Tier.STANDARD: {"pattern": r"gemini-[\d.]+-?flash(?!-lite)", "default": "gemini-3-flash"},
        Tier.LIGHT:    {"pattern": r"gemini-[\d.]+-?flash-lite", "default": "gemini-3-flash-lite"},
    },
    "deepseek": {
        Tier.FLAGSHIP: {"pattern": r"deepseek-(reasoner|r\d|chat)", "default": "deepseek-chat"},
        Tier.STANDARD: {"pattern": r"deepseek-chat", "default": "deepseek-chat"},
        Tier.LIGHT:    {"pattern": r"deepseek-chat", "default": "deepseek-chat"},
    },
}


def _version_key(model_id: str) -> tuple:
    """Sortable version tuple from a model id (higher = newer)."""
    nums = re.findall(r"\d+", model_id)
    return tuple(int(x) for x in nums) or (0,)


def _latest(available: list[str], pattern: str) -> str | None:
    rx = re.compile(pattern, re.I)
    matches = [m for m in available if rx.search(m)]
    if not matches:
        return None
    return max(matches, key=_version_key)


def resolve_model(family: str, tier: Tier | str, available: list[str] | None = None) -> str:
    """Resolve a concrete model id for a family + tier.

    Priority: per-family env (``NEUROAION_CLAUDE_FLAGSHIP``) → global tier env
    (``NEUROAION_MODEL_FLAGSHIP``) → newest model in *available* matching the
    tier pattern → the family default. This keeps the choice current without
    code changes.
    """
    fam = normalize_family(family)
    tier = Tier(tier) if not isinstance(tier, Tier) else tier
    spec = FAMILY_MODELS.get(fam, FAMILY_MODELS["claude"])[tier]
    env_fam = os.environ.get(f"NEUROAION_{fam.upper()}_{tier.name}", "").strip()
    if env_fam:
        return env_fam
    env_global = os.environ.get(f"NEUROAION_MODEL_{tier.name}", "").strip()
    if env_global:
        return env_global
    if available:
        latest = _latest(available, spec["pattern"])
        if latest:
            return latest
    return spec["default"]


def plan(family: str, available: list[str] | None = None) -> dict[str, dict]:
    """Full stage -> {tier, model} routing plan for a family."""
    fam = normalize_family(family)
    out: dict[str, dict] = {}
    for stage, tier in STAGE_TIER.items():
        out[stage] = {"tier": tier.value, "model": resolve_model(fam, tier, available)}
    return out


def routing_json(available: list[str] | None = None) -> dict:
    """Machine-readable routing for every supported family (for cowork handlers)."""
    return {
        "tiers": {t.name: t.value for t in Tier},
        "stage_tier": {s: t.value for s, t in STAGE_TIER.items()},
        "families": {fam: plan(fam, available) for fam in FAMILY_MODELS},
    }


def routing_markdown() -> str:
    """Human-readable routing table (stage x family), for docs."""
    fams = list(FAMILY_MODELS)
    head = "| Stage | Tier | " + " | ".join(f.capitalize() for f in fams) + " |"
    sep = "|" + "---|" * (len(fams) + 2)
    rows = [head, sep]
    for stage, tier in STAGE_TIER.items():
        cells = " | ".join(resolve_model(f, tier) for f in fams)
        rows.append(f"| {stage} | {tier.value} | {cells} |")
    return "\n".join(rows)
