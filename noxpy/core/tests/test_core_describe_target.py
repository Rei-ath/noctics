import os

from central.core import ChatClient


def test_describe_target_reports_config(monkeypatch):
    monkeypatch.delenv("NOX_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    client = ChatClient(
        url="http://example.com",
        model="test-model",
        temperature=0.3,
        max_tokens=256,
        stream=True,
        sanitize=True,
        enable_logging=False,
        strip_reasoning=False,
    )

    info = client.describe_target()

    assert info["model"] == "test-model"
    assert info["url"] == "http://example.com"
    assert info["stream"] is True
    assert info["sanitize"] is True
    assert info["strip_reasoning"] is False
    assert info["logging_enabled"] is False
    assert info["has_api_key"] is False
    assert info["temperature"] == 0.3
    assert info["max_tokens"] == 256
    assert info["central_name"] == "nox"
    assert info["central_scale"] == "nox"
    assert info["noctics_variant"] == "nox"
    assert info["model_target"] == "qwen2.5:0.5b"
    assert info["target_model"] == "test-model"


def test_openai_model_mapping(monkeypatch):
    monkeypatch.setenv("NOCTICS_SKIP_DOTENV", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("NOX_TARGET_MODEL", raising=False)
    monkeypatch.setenv("NOX_OPENAI_MODEL", "gpt-4o-mini")

    client = ChatClient(
        url="https://api.openai.com/v1/chat/completions",
        model="nox",
        enable_logging=False,
    )

    info = client.describe_target()

    assert info["model"] == "nox"
    assert info["target_model"] == os.getenv("NOX_OPENAI_MODEL", "gpt-4o-mini")


def test_openai_payload_structure(monkeypatch):
    monkeypatch.setenv("NOCTICS_SKIP_DOTENV", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("NOX_OPENAI_MODEL", "gpt-4o-mini")

    client = ChatClient(
        url="https://api.openai.com/v1/chat/completions",
        model="nox",
        enable_logging=False,
    )

    raw_payload = {
        "model": "nox",
        "system": "Be helpful",
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
        "options": {"temperature": 0.7},
    }

    adjusted = client._prepare_payload(raw_payload, stream=False)

    assert adjusted["model"] == "gpt-4o-mini"
    assert adjusted["messages"][0]["role"] == "system"
    assert adjusted["messages"][0]["content"] == "Be helpful"
    assert {msg["role"] for msg in adjusted["messages"]} >= {"user", "assistant", "system"}
    assert "options" not in adjusted
