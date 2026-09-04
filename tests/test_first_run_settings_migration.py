import json

import modules.settings as settings_module


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
    assert json.loads(config_file.read_text(encoding="utf-8"))["first_run"]["completed"] is True


def test_existing_explicit_incomplete_first_run_is_not_overridden(monkeypatch, tmp_path):
    defaults = {"first_run": {"completed": False}, "language": "zh_CN"}
    config_file = _configure_paths(monkeypatch, tmp_path, defaults)
    config_file.parent.mkdir(parents=True)
    config_file.write_text(json.dumps({"first_run": {"completed": False}}), encoding="utf-8")

    store = settings_module.Settings()

    assert store.get("first_run.completed") is False
