"""OpenAI-compatible provider (DeepSeek etc.) and provider routing."""
from neuroaion.llm import (MockProvider, OpenAICompatibleProvider,
                           _parse_json_lenient, build_provider)


def test_parse_json_lenient_handles_fences_and_prose():
    assert _parse_json_lenient('{"a": 1}') == {"a": 1}
    assert _parse_json_lenient('```json\n{"a": 2}\n```') == {"a": 2}
    assert _parse_json_lenient('Sure! {"a": 3} done.') == {"a": 3}


def test_build_provider_falls_back_to_mock_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert isinstance(build_provider("deepseek"), MockProvider)
    assert isinstance(build_provider("mock"), MockProvider)


def test_openai_compatible_json_and_text(monkeypatch):
    p = OpenAICompatibleProvider(base_url="https://api.deepseek.com",
                                 api_key="sk-test", model="deepseek-v4-pro")
    captured = {}

    def fake_post(messages, *, max_tokens, json_mode):
        captured["json_mode"] = json_mode
        captured["model_in_msgs"] = messages
        return '```json\n{"decision": "include", "confidence": 0.9}\n```' if json_mode \
            else "Some written narrative."

    monkeypatch.setattr(p, "_post", fake_post)

    out = p.complete_json(system="screen", user="a record",
                          schema={"type": "object"}, cache_prefix="PROTOCOL")
    assert out == {"decision": "include", "confidence": 0.9}
    assert captured["json_mode"] is True
    # The cache prefix and schema are folded into the system message.
    assert "PROTOCOL" in captured["model_in_msgs"][0]["content"]

    txt = p.complete_text(system="write", user="synthesise")
    assert txt == "Some written narrative."
    assert captured["json_mode"] is False
