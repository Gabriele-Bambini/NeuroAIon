"""Cowork provider: the pipeline runs on an agent's subscription (no API key)."""
from neuroaion import config, llm


def teardown_function(_):
    llm.set_cowork_handler(None)
    config.PROVIDER = "anthropic"
    config.COWORK_DIR = ""


def test_provider_ready_reflects_cowork_binding(monkeypatch):
    monkeypatch.setattr(config, "have_api_key", lambda: False)
    config.PROVIDER = "anthropic"
    config.COWORK_DIR = ""
    llm.set_cowork_handler(None)
    assert llm.provider_ready() is False          # no key, no cowork → not ready
    llm.set_cowork_handler(lambda **k: {})
    assert llm.provider_ready() is True            # cowork handler bound → ready


def test_cowork_handler_serves_json_and_text():
    calls = {}

    def handler(*, kind, system, user, schema, cache_prefix, max_tokens):
        calls[kind] = (system, user)
        if kind == "json":
            return {"decision": "include", "reason": "on topic"}
        return "A model-authored narrative."

    llm.set_cowork_handler(handler)
    p = llm.CoworkProvider()
    out = p.complete_json(system="s", user="TITLE: X", schema={"type": "object"})
    assert out["decision"] == "include"
    assert p.complete_text(system="s", user="write") == "A model-authored narrative."
    assert "json" in calls and "text" in calls


def test_cowork_disk_queue_roundtrip(tmp_path):
    # No handler → requests are queued to disk; a written answer is then served.
    llm.set_cowork_handler(None)
    p = llm.CoworkProvider(response_dir=str(tmp_path))
    try:
        p.complete_json(system="s", user="u", schema={"type": "object"})
        assert False, "should have raised CoworkPending"
    except llm.CoworkPending:
        pass
    reqs = list((tmp_path / "requests").glob("*.json"))
    assert len(reqs) == 1
    key = reqs[0].stem
    (tmp_path / "responses").mkdir(exist_ok=True)
    (tmp_path / "responses" / f"{key}.json").write_text('{"ok": true}', encoding="utf-8")
    assert p.complete_json(system="s", user="u", schema={"type": "object"}) == {"ok": True}


def test_get_provider_prefers_cowork_when_selected():
    config.PROVIDER = "cowork"
    llm.set_cowork_handler(lambda **k: {})
    assert isinstance(llm.get_provider(mock=False), llm.CoworkProvider)
    # Explicit mock still wins.
    assert isinstance(llm.get_provider(mock=True), llm.MockProvider)


def test_orchestrator_not_mock_when_cowork_bound(monkeypatch):
    from neuroaion.orchestrator import Orchestrator
    monkeypatch.setattr(config, "have_api_key", lambda: False)
    config.PROVIDER = "cowork"
    llm.set_cowork_handler(lambda **k: {})
    orch = Orchestrator({"title": "t"}, live_sources=False)
    assert orch.mock is False                      # cowork is a real provider
