import json

import modules.settings as settings_module
from modules.runtime_dependencies import RuntimeDependencyManager


def _configure_paths(monkeypatch, tmp_path, defaults):
    config_dir = tmp_path / "user" / "config"
    config_file = config_dir / "settings.json"
    default_file = tmp_path / "program" / "config" / "default_settings.json"
    default_file.parent.mkdir(parents=True)
    default_file.write_text(json.dumps(defaults), encoding="utf-8")
    monkeypatch.setattr(settings_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(settings_module, "CONFIG_FILE", config_file)
    monkeypatch.setattr(settings_module, "DEFAULT_SETTINGS_FILE", default_file)
    return config_file


def test_new_user_keeps_first_run_incomplete(monkeypatch, tmp_path):
    defaults = {"first_run": {"completed": False}, "language": "zh_CN"}
    config_file = _configure_paths(monkeypatch, tmp_path, defaults)

    store = settings_module.Settings()

    assert store.get("first_run.completed") is False
    assert json.loads(config_file.read_text(encoding="utf-8"))["first_run"]["completed"] is False


def test_existing_user_without_first_run_field_is_migrated_once(monkeypatch, tmp_path):
    defaults = {"first_run": {"completed": False}, "language": "zh_CN"}
    config_file = _configure_paths(monkeypatch, tmp_path, defaults)
    config_file.parent.mkdir(parents=True)
    config_file.write_text(json.dumps({"language": "en_US", "chat_model": "llama3.1:8b"}), encoding="utf-8")

    store = settings_module.Settings()

    assert store.get("first_run.completed") is True
    assert store.get("chat_model") == "llama3.1:8b"
    assert store.get("chat_model_mode") == "manual"
    assert json.loads(config_file.read_text(encoding="utf-8"))["first_run"]["completed"] is True


def test_existing_explicit_incomplete_first_run_is_not_overridden(monkeypatch, tmp_path):
    defaults = {"first_run": {"completed": False}, "language": "zh_CN"}
    config_file = _configure_paths(monkeypatch, tmp_path, defaults)
    config_file.parent.mkdir(parents=True)
    config_file.write_text(json.dumps({"first_run": {"completed": False}}), encoding="utf-8")

    store = settings_module.Settings()

    assert store.get("first_run.completed") is False


def test_existing_user_receives_ollama_request_policy_defaults(monkeypatch, tmp_path):
    defaults = {
        "first_run": {"completed": False},
        "language": "zh_CN",
        "ollama": {
            "host": "http://127.0.0.1:11434",
            "thinking_mode": "off",
            "keep_alive": "30m",
        },
    }
    config_file = _configure_paths(monkeypatch, tmp_path, defaults)
    config_file.parent.mkdir(parents=True)
    config_file.write_text(json.dumps({
        "first_run": {"completed": True},
        "ollama": {"host": "http://localhost:11434"},
    }), encoding="utf-8")

    store = settings_module.Settings()

    assert store.get("ollama.host") == "http://localhost:11434"
    assert store.get("ollama.thinking_mode") == "off"
    assert store.get("ollama.keep_alive") == "30m"


def test_empty_legacy_chat_selection_migrates_to_auto(monkeypatch, tmp_path):
    defaults = {
        "first_run": {"completed": False},
        "language": "zh_CN",
        "chat_model": "",
        "chat_model_mode": "auto",
    }
    config_file = _configure_paths(monkeypatch, tmp_path, defaults)
    config_file.parent.mkdir(parents=True)
    config_file.write_text(json.dumps({"chat_model": ""}), encoding="utf-8")

    store = settings_module.Settings()

    assert store.get("chat_model_mode") == "auto"


def test_auto_resolved_model_persists_across_real_settings_reload(monkeypatch, tmp_path):
    defaults = {
        "first_run": {"completed": False},
        "language": "zh_CN",
        "chat_model_mode": "auto",
        "chat_model": "",
        "resolved_chat_model": "",
        "chat_model_resolution_reason": "",
        "last_successful_chat_model": "",
        "embedding_model_mode": "manual",
        "embedding_model": "",
        "resolved_embedding_model": "",
        "embedding_model_resolution_reason": "",
    }
    _configure_paths(monkeypatch, tmp_path, defaults)
    store = settings_module.Settings()
    manager = RuntimeDependencyManager(
        store,
        which=lambda _name: None,
        bundled_tool_finder=lambda _name: None,
        module_finder=lambda _name: None,
        ollama_api_probe=lambda _host, _timeout: {
            "available": True,
            "models": [{"name": "qwen3:4b"}],
        },
        hardware_probe=lambda: {
            "ram_gb": 8,
            "logical_cores": 4,
            "vram_gb": None,
            "disk_free_gb": 20,
        },
        environment={},
    )

    manager.check_models()
    restarted = settings_module.Settings()

    assert restarted.get("chat_model_mode") == "auto"
    assert restarted.get("chat_model") == "qwen3:4b"
    assert restarted.get("resolved_chat_model") == "qwen3:4b"
    assert restarted.get("last_successful_chat_model") == "qwen3:4b"
