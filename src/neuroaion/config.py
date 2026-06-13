"""Runtime configuration: environment, model selection, and protocol loading."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

# The model every agent runs on. Opus 4.8 is the default and recommended choice.
DEFAULT_MODEL = os.environ.get("NEUROAION_MODEL", "claude-opus-4-8")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "").strip()
CONTACT_EMAIL = os.environ.get("NEUROAION_CONTACT_EMAIL", "").strip() or "neuroaion@example.org"
MAX_WORKERS = int(os.environ.get("NEUROAION_MAX_WORKERS", "8"))

# User-Agent string used for all literature-API calls (polite-pool etiquette).
USER_AGENT = f"NeuroAIon/0.1 (systematic-review-engine; mailto:{CONTACT_EMAIL})"


def have_api_key() -> bool:
    """True if a live Anthropic key is configured. Otherwise the engine runs mock."""
    return bool(ANTHROPIC_API_KEY)


def load_protocol_file(path: str | Path) -> dict:
    """Load a YAML protocol seed file into a plain dict."""
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Protocol file {path} must be a YAML mapping at the top level.")
    return data
