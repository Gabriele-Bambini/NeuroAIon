"""Model-tier routing: right model per task, per agent family, dynamically."""
from neuroaion import routing
from neuroaion.routing import Tier


def test_stage_tiers():
    assert routing.tier_for("screen_ta") is Tier.LIGHT
    assert routing.tier_for("extraction") is Tier.FLAGSHIP
    assert routing.tier_for("eligibility") is Tier.STANDARD
    assert routing.tier_for("unknown-stage") is Tier.STANDARD   # safe default


def test_family_normalization():
    assert routing.normalize_family("Claude Code") == "claude"
    assert routing.normalize_family("anthropic") == "claude"
    assert routing.normalize_family("codex") == "openai"
    assert routing.normalize_family("Antigravity") == "gemini"
    assert routing.normalize_family("deepseek") == "deepseek"


def test_defaults_per_family_and_tier():
    assert routing.resolve_model("claude", Tier.FLAGSHIP) == "claude-opus-4-8"
    assert routing.resolve_model("claude", Tier.STANDARD) == "claude-sonnet-5"
    assert routing.resolve_model("claude", Tier.LIGHT) == "claude-haiku-4-5"
    assert "pro" in routing.resolve_model("gemini", Tier.FLAGSHIP)


def test_latest_by_pattern_auto_upgrades():
    # A newer Opus in the available list is chosen automatically (Opus 4.9 > 4.8).
    available = ["claude-opus-4-8", "claude-opus-4-9", "claude-sonnet-5", "claude-haiku-4-5"]
    assert routing.resolve_model("claude", Tier.FLAGSHIP, available) == "claude-opus-4-9"
    available2 = ["claude-opus-5-0", "claude-opus-4-9"]
    assert routing.resolve_model("claude", Tier.FLAGSHIP, available2) == "claude-opus-5-0"


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("NEUROAION_CLAUDE_FLAGSHIP", "claude-opus-9-9")
    assert routing.resolve_model("claude", Tier.FLAGSHIP) == "claude-opus-9-9"
    monkeypatch.delenv("NEUROAION_CLAUDE_FLAGSHIP")
    monkeypatch.setenv("NEUROAION_MODEL_LIGHT", "some-cheap-model")
    assert routing.resolve_model("openai", Tier.LIGHT) == "some-cheap-model"


def test_plan_and_json_shapes():
    p = routing.plan("claude")
    assert p["reporter"]["tier"] == "flagship" and p["reporter"]["model"] == "claude-opus-4-8"
    j = routing.routing_json()
    assert set(j["tiers"]) == {"FLAGSHIP", "STANDARD", "LIGHT"}
    assert "claude" in j["families"] and "openai" in j["families"] and "gemini" in j["families"]
