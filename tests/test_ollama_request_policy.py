import json
from pathlib import Path

import pytest

from modules.ollama_request_policy import (
    DEFAULT_KEEP_ALIVE,
    DEFAULT_THINKING_MODE,
    normalize_keep_alive,
    resolve_ollama_request_policy,
)


class Settings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


@pytest.mark.parametrize(
    ("mode", "present", "value"),
    [
        ("off", True, False),
        ("on", True, True),
        ("default", False, None),
    ],
)
def test_thinking_modes_map_at_the_single_payload_boundary(mode, present, value):
    policy = resolve_ollama_request_policy(Settings({
        "ollama.thinking_mode": mode,
        "ollama.keep_alive": None,
    }))
    payload = {"model": "model", "messages": [], "stream": True}

    returned = policy.apply(payload)

    assert returned is payload
    assert policy.thinking_mode == mode
    assert policy.think_payload_value is value
    assert ("think" in payload) is present
    if present:
        assert payload["think"] is value
    assert "keep_alive" not in payload
    assert payload["model"] == "model"
    assert payload["messages"] == []
    assert payload["stream"] is True


def test_configured_keep_alive_is_combined_without_overwriting_payload_fields():
    policy = resolve_ollama_request_policy(Settings({
        "ollama.thinking_mode": "on",
        "ollama.keep_alive": "1h30m",
    }))
    payload = {"model": "model", "messages": [{"role": "user"}], "stream": True}

    policy.apply(payload)

    assert payload == {
        "model": "model",
        "messages": [{"role": "user"}],
        "stream": True,
        "think": True,
        "keep_alive": "1h30m",
    }
    assert policy.diagnostics() == {
        "ollama_think_mode": "on",
        "think_payload_value": True,
        "ollama_keep_alive": "1h30m",
    }


@pytest.mark.parametrize("value", [None, "", " default "])
def test_disabled_or_default_keep_alive_is_omitted(value):
    policy = resolve_ollama_request_policy(Settings({
        "ollama.thinking_mode": "default",
        "ollama.keep_alive": value,
    }))
    payload = {"model": "model"}

    policy.apply(payload)

    assert "think" not in payload
    assert "keep_alive" not in payload
    assert policy.keep_alive is None


def test_invalid_persisted_policy_uses_safe_runtime_fallbacks():
    policy = resolve_ollama_request_policy(Settings({
        "ollama.thinking_mode": "invalid",
        "ollama.keep_alive": "forever",
    }))
    payload = {}

    policy.apply(payload)

    assert policy.thinking_mode == DEFAULT_THINKING_MODE
    assert payload == {"think": False}
    assert policy.keep_alive is None


def test_invalid_request_local_thinking_override_is_rejected():
    with pytest.raises(ValueError, match="thinking mode"):
        resolve_ollama_request_policy(Settings(), thinking_mode="invalid")


@pytest.mark.parametrize(
    "duration",
    ["0", "250ms", "30m", "1h30m", "1.5h"],
)
def test_supported_ollama_duration_strings_are_preserved(duration):
    assert normalize_keep_alive(duration) == duration


@pytest.mark.parametrize("duration", [-1, "-1", "30 minutes", "30M", object()])
def test_non_duration_keep_alive_values_are_rejected(duration):
    with pytest.raises(ValueError, match="keep_alive"):
        normalize_keep_alive(duration)


def test_default_and_example_config_publish_realtime_policy_defaults():
    project_root = Path(__file__).parents[1]
    for relative_path in ("config/default_settings.json", "config/settings.example.json"):
        data = json.loads((project_root / relative_path).read_text(encoding="utf-8-sig"))
        assert data["ollama"]["thinking_mode"] == DEFAULT_THINKING_MODE
        assert data["ollama"]["keep_alive"] == DEFAULT_KEEP_ALIVE
