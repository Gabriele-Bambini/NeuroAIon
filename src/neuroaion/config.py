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

# Provider selection. "anthropic" (default) or any OpenAI-compatible backend
# ("deepseek", "openai", "custom"). A separate provider can drive the high-volume
# screening stage (e.g. DeepSeek) while a premium model handles redaction.
PROVIDER = os.environ.get("NEUROAION_PROVIDER", "anthropic").strip().lower()
SCREEN_PROVIDER = os.environ.get("NEUROAION_SCREEN_PROVIDER", "").strip().lower()
SCREEN_MODEL = os.environ.get("NEUROAION_SCREEN_MODEL", "").strip()

# OpenAI-compatible endpoints (DeepSeek V-series, OpenAI, Qwen, local vLLM/Ollama...).
# base_url + key env + default model, per provider name.
OPENAI_COMPATIBLE = {
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY", "deepseek-chat"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4.1-mini"),
    "custom": (os.environ.get("NEUROAION_BASE_URL", ""), "NEUROAION_API_KEY", ""),
}

# Cowork mode: the pipeline is driven by a controlling agent (e.g. Claude Code on
# a monthly subscription) that answers every LLM call itself — no API key. Set
# NEUROAION_PROVIDER=cowork, and either bind llm.set_cowork_handler(...) or point
# NEUROAION_COWORK_DIR at a request/response queue directory.
COWORK_DIR = os.environ.get("NEUROAION_COWORK_DIR", "").strip()

NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "").strip()
CONTACT_EMAIL = os.environ.get("NEUROAION_CONTACT_EMAIL", "").strip() or "neuroaion@example.org"
MAX_WORKERS = int(os.environ.get("NEUROAION_MAX_WORKERS", "8"))

# User-Agent string used for all literature-API calls (polite-pool etiquette).
USER_AGENT = f"NeuroAIon/0.1 (systematic-review-engine; mailto:{CONTACT_EMAIL})"


def have_api_key() -> bool:
    """True if a live LLM backend is configured. Otherwise the engine runs mock."""
    if PROVIDER == "anthropic":
        return bool(ANTHROPIC_API_KEY)
    base, keyenv, _ = OPENAI_COMPATIBLE.get(PROVIDER, OPENAI_COMPATIBLE["custom"])
    return bool(os.environ.get(keyenv, "").strip())


def load_protocol_file(path: str | Path) -> dict:
    """Load a YAML protocol seed file into a plain dict."""
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Protocol file {path} must be a YAML mapping at the top level.")
    return data
