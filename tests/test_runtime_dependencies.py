import json
from pathlib import Path

import pytest

from modules.runtime_dependencies import (
    OllamaRuntimeState,
    RuntimeDependencyManager,
    RuntimeStatus,
    classify_ollama_models,
    persist_manual_model_selection,
    resolve_ollama_executable,
)
from modules.startup_diagnostics import _voice_check


READY_MODELS = [
    {
        "name": "qwen3:8b",
        "digest": "chat-digest",
        "details": {"parameter_size": "8.2B"},
    },
    {
        "name": "nomic-embed-text:latest",
        "digest": "embed-digest",
        "details": {"parameter_size": "137M"},
    },
]


def _api(available, models=(), reason="offline"):
    return lambda _host, _timeout: {
        "available": available,
        "models": list(models),
        "reason": "API available" if available else reason,
        "http_status": 200 if available else None,
    }


def _finder(installed=()):
    names = set(installed)
    return lambda name: object() if name in names else None


class _SettingsStore:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.saved = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def update_many(self, values, save=True):
        self.values.update(values)
        self.saved.append((dict(values), save))


def _manager(
    *,
    settings=None,
    executable=None,
    ffmpeg=None,
    available=False,
    models=(),
    modules=(),
    microphone=(False, "No microphone"),
    playback=(False, "No output"),
    whisper=(False, "Not cached"),
    hardware=None,
):
    return RuntimeDependencyManager(
        settings or {},
        which=lambda name: (
            executable
            if name in {"ollama", "ollama.exe"}
            else ffmpeg
            if name in {"ffmpeg", "ffmpeg.exe"}
            else None
        ),
        bundled_tool_finder=lambda _name: None,
        module_finder=_finder(modules),
        module_importer=lambda _name: object(),
        tts_service_probe=lambda _timeout: (True, "Test service available"),
        ffmpeg_probe=lambda _path: True,
        ollama_api_probe=_api(available, models),
        microphone_probe=lambda: microphone,
        playback_device_probe=lambda: playback,
        whisper_model_probe=lambda _model: whisper,
        hardware_probe=lambda: hardware
        or {
            "ram_gb": 16,
            "cpu": "Test CPU",
            "logical_cores": 8,
            "gpu": None,
            "vram_gb": None,
            "disk_free_gb": 50,
        },
        environment={},
    )


def test_status_vocabulary_is_stable():
    assert {status.value for status in RuntimeStatus} == {
        "Ready",
        "Missing",
        "Offline",
        "Optional",
        "Degraded",
    }


def test_ollama_missing_is_distinct_from_offline():
    report = _manager().check_ollama()

    assert report["state"] == OllamaRuntimeState.NOT_INSTALLED.value
    assert report["executable"]["status"] == RuntimeStatus.MISSING.value
    assert report["service"]["status"] == RuntimeStatus.OFFLINE.value


def test_ollama_installed_server_offline_is_reported_separately():
    report = _manager(executable=r"C:\Program Files\Ollama\ollama.exe").check_ollama()

    assert report["state"] == OllamaRuntimeState.INSTALLED_OFFLINE.value
    assert report["executable"]["status"] == RuntimeStatus.READY.value
    assert report["service"]["status"] == RuntimeStatus.OFFLINE.value


def test_ollama_ready_without_models_keeps_model_states_explicit():
    report = _manager(available=True).check_ollama()

    assert report["state"] == OllamaRuntimeState.SERVER_READY.value
    assert report["service"]["status"] == RuntimeStatus.READY.value
    assert report["chat_model"]["status"] == RuntimeStatus.MISSING.value
    assert report["embedding_model"]["status"] == RuntimeStatus.OPTIONAL.value


def test_ollama_models_are_split_into_chat_and_embedding_only():
    report = _manager(available=True, models=READY_MODELS).check_ollama()

    assert [item["name"] for item in report["models"]["chat"]] == ["qwen3:8b"]
    assert [item["name"] for item in report["models"]["embedding"]] == [
        "nomic-embed-text:latest"
    ]
    assert report["models"]["embedding"][0]["chat_supported"] is False
    assert report["chat_model"]["status"] == RuntimeStatus.DEGRADED.value
    assert report["embedding_model"]["status"] == RuntimeStatus.OPTIONAL.value


def test_one_chat_model_without_selection_is_auto_resolved_and_ready():
    report = _manager(available=True, models=["qwen3:4b"]).check()

    assert report["ollama"]["chat_model"]["status"] == RuntimeStatus.READY.value
    assert report["model_resolution"]["chat"]["model"] == "qwen3:4b"
    assert report["ollama"]["chat_model"]["detail"] == "Auto-selected: qwen3:4b"
    assert report["recommendation"]["download_required"] is False


def test_multiple_chat_models_use_installed_hardware_recommendation():
    report = _manager(
        available=True,
        models=["qwen3:4b", "qwen3:8b", "qwen3:14b"],
    ).check()

    assert report["model_resolution"]["chat"]["model"] == "qwen3:8b"
    assert report["model_resolution"]["chat"]["reason"] == "hardware_recommendation"
    assert report["recommendation"]["download_required"] is False


def test_manual_pinned_model_is_preserved():
    settings = {"chat_model_mode": "manual", "chat_model": "qwen3:4b"}
    report = _manager(
        settings=settings,
        available=True,
        models=["qwen3:4b", "qwen3:14b"],
    ).check()

    assert report["model_resolution"]["chat"]["model"] == "qwen3:4b"
    assert report["ollama"]["chat_model"]["detail"] == "Selected: qwen3:4b"


def test_valid_auto_model_is_stable_when_another_model_is_installed():
    settings = {
        "chat_model_mode": "auto",
        "chat_model": "qwen3:4b",
        "resolved_chat_model": "qwen3:4b",
        "last_successful_chat_model": "qwen3:4b",
        "chat_model_resolution_reason": "only_compatible_model",
    }
    report = _manager(
        settings=settings,
        available=True,
        models=["qwen3:4b", "qwen3:14b"],
    ).check()

    assert report["model_resolution"]["chat"]["model"] == "qwen3:4b"
    assert report["model_resolution"]["chat"]["reason"] == "only_compatible_model"


def test_deleted_auto_model_falls_back_to_remaining_chat_model():
    settings = {
        "chat_model_mode": "auto",
        "chat_model": "qwen3:4b",
        "resolved_chat_model": "qwen3:4b",
        "last_successful_chat_model": "qwen3:4b",
    }
    report = _manager(
        settings=settings,
        available=True,
        models=["qwen3:14b"],
    ).check()

    assert report["model_resolution"]["chat"]["model"] == "qwen3:14b"
    assert report["model_resolution"]["chat"]["reason"] == "previous_model_unavailable"


def test_only_embedding_model_never_resolves_as_chat():
    report = _manager(
        available=True,
        models=["nomic-embed-text:latest"],
    ).check()

    assert report["model_resolution"]["chat"]["model"] == ""
    assert report["ollama"]["chat_model"]["status"] == RuntimeStatus.MISSING.value
    assert report["ollama"]["models"]["chat"] == []


def test_embedding_auto_resolution_is_optional_and_capability_safe():
    settings = {
        "embedding_model_mode": "auto",
        "embedding_model": "",
        "resolved_embedding_model": "",
    }
    report = _manager(
        settings=settings,
        available=True,
        models=["qwen3:4b", "nomic-embed-text:latest"],
    ).check()

    assert report["model_resolution"]["chat"]["model"] == "qwen3:4b"
    assert report["model_resolution"]["embedding"]["model"] == "nomic-embed-text:latest"
    assert "qwen3:4b" not in report["ollama"]["embedding_model"]["data"]["models"]
    assert report["ollama"]["embedding_model"]["required"] is False


def test_auto_resolution_is_persisted_and_survives_restart():
    store = _SettingsStore({"chat_model_mode": "auto", "chat_model": ""})
    first = _manager(
        settings=store,
        available=True,
        models=["qwen3:4b"],
    ).check()

    assert first["model_resolution"]["persisted"] is True
    assert store.values["resolved_chat_model"] == "qwen3:4b"
    assert store.values["last_successful_chat_model"] == "qwen3:4b"

    restarted = _manager(
        settings=store,
        available=True,
        models=["qwen3:4b", "qwen3:14b"],
    ).check()
    assert restarted["model_resolution"]["chat"]["model"] == "qwen3:4b"


def test_explicit_reevaluation_can_change_a_valid_auto_model():
    settings = {
        "chat_model_mode": "auto",
        "chat_model": "qwen3:4b",
        "resolved_chat_model": "qwen3:4b",
        "last_successful_chat_model": "qwen3:4b",
    }
    manager = _manager(
        settings=settings,
        available=True,
        models=["qwen3:4b", "qwen3:8b"],
    )

    normal = manager.check()
    reevaluated = manager.check(reevaluate_models=True)

    assert normal["model_resolution"]["chat"]["model"] == "qwen3:4b"
    assert reevaluated["model_resolution"]["chat"]["model"] == "qwen3:8b"
    assert reevaluated["model_resolution"]["chat"]["reason"] == "explicit_reevaluation"


def test_offline_check_preserves_selection_and_does_not_write_settings():
    store = _SettingsStore(
        {
            "chat_model_mode": "auto",
            "chat_model": "qwen3:4b",
            "resolved_chat_model": "qwen3:4b",
        }
    )

    report = _manager(settings=store, available=False).check()

    assert report["ollama"]["chat_model"]["status"] == RuntimeStatus.OFFLINE.value
    assert report["model_resolution"]["chat"]["model"] == "qwen3:4b"
    assert store.saved == []


def test_configured_models_are_ready_only_when_the_selected_model_exists():
    report = _manager(
        settings={
            "chat_model": "qwen3:8b",
            "embedding_model": "nomic-embed-text",
        },
        available=True,
        models=READY_MODELS,
    ).check_ollama()

    assert report["chat_model"]["status"] == RuntimeStatus.READY.value
    assert report["embedding_model"]["status"] == RuntimeStatus.READY.value


def test_configured_latest_tag_matches_untagged_installed_model():
    manager = _manager(
        settings={"chat_model": "qwen3:8b:latest"},
        available=True,
        models=["qwen3:8b"],
    )
    # This deliberately remains unavailable: only the conventional terminal
    # ':latest' suffix is normalized, not arbitrary double-tag model names.
    assert manager.check_ollama()["chat_model"]["data"]["configured_available"] is False

    manager = _manager(
        settings={"chat_model": "qwen3"},
        available=True,
        models=["qwen3:latest"],
    )
    assert manager.check_ollama()["chat_model"]["data"]["configured_available"] is True


def test_model_catalog_matches_existing_first_run_fetcher_contract():
    catalog = _manager(available=True, models=READY_MODELS).model_catalog()

    assert catalog["ok"] is True
    assert catalog["state"] == OllamaRuntimeState.SERVER_READY.value
    assert catalog["models"] == catalog["chat_models"] + catalog["embedding_models"]


def test_model_normalization_deduplicates_names_case_insensitively():
    models = classify_ollama_models(["QWEN3:8B", {"name": "qwen3:8b"}, ""])

    assert len(models["all"]) == 1
    assert models["all"][0]["capability"] == "Chat Supported"


def test_malformed_model_list_is_contained():
    manager = RuntimeDependencyManager(
        {},
        which=lambda _name: None,
        bundled_tool_finder=lambda _name: None,
        module_finder=_finder(),
        ollama_api_probe=lambda _host, _timeout: {
            "available": True,
            "models": "not-a-list",
        },
        hardware_probe=lambda: {},
        environment={},
    )

    report = manager.check_models()

    assert report["ollama"]["models"]["all"] == []
    assert report["ollama"]["chat_model"]["status"] == RuntimeStatus.MISSING.value


def test_manual_selection_helper_records_pinned_state():
    store = _SettingsStore()

    values = persist_manual_model_selection(store, "qwen3:4b", kind="chat")

    assert values["chat_model_mode"] == "manual"
    assert store.values["chat_model"] == "qwen3:4b"
    assert store.values["resolved_chat_model"] == ""


def test_ffmpeg_resolution_prefers_bundled_then_configured_then_path(tmp_path):
    bundled = tmp_path / "bundle" / "ffmpeg.exe"
    configured = tmp_path / "custom" / "ffmpeg.exe"
    bundled.parent.mkdir()
    configured.parent.mkdir()
    bundled.touch()
    configured.touch()

    manager = RuntimeDependencyManager(
        {"voice": {"recorder": {"ffmpeg_path": str(configured)}}},
        bundled_tool_finder=lambda name: bundled if name == "ffmpeg" else None,
        which=lambda _name: r"C:\PATH\ffmpeg.exe",
        ollama_api_probe=_api(False),
    )
    report = manager.check_ffmpeg()
    assert report["data"]["source"] == "bundled"
    assert report["data"]["path"] == str(bundled)

    bundled.unlink()
    report = manager.check_ffmpeg()
    assert report["data"]["source"] == "configured"
    assert report["data"]["path"] == str(configured)

    configured.unlink()
    report = manager.check_ffmpeg()
    assert report["data"]["source"] == "PATH"


def test_ffmpeg_missing_is_non_required_dependency():
    ffmpeg = _manager().check_ffmpeg()

    assert ffmpeg["status"] == RuntimeStatus.MISSING.value
    assert ffmpeg["required"] is False
    assert ffmpeg["available"] is False


def test_disabled_voice_dependencies_are_optional():
    voice = _manager(settings={"voice": {"enabled": False}}).check_voice()

    assert voice["status"] == RuntimeStatus.OPTIONAL.value
    assert all(item["status"] == RuntimeStatus.OPTIONAL.value for item in voice["items"])


def test_disabled_voice_does_not_probe_microphone_playback_or_whisper():
    calls = []
    manager = RuntimeDependencyManager(
        {"voice": {"enabled": False}},
        which=lambda _name: None,
        bundled_tool_finder=lambda _name: None,
        module_finder=_finder(
            {"faster_whisper", "ctranslate2", "edge_tts", "pygame"}
        ),
        microphone_probe=lambda: calls.append("microphone"),
        playback_device_probe=lambda: calls.append("playback"),
        whisper_model_probe=lambda _model: calls.append("whisper"),
        environment={},
    )

    voice = manager.check_voice(
        ffmpeg={"available": True, "detail": "FFmpeg is installed."}
    )

    assert calls == []
    assert voice["status"] == RuntimeStatus.OPTIONAL.value
    microphone = next(item for item in voice["items"] if item["key"] == "microphone")
    assert "will not enumerate microphone devices" in microphone["detail"]


def test_disabled_startup_diagnostics_skip_the_dependency_manager(monkeypatch):
    class UnexpectedManager:
        def __init__(self, _settings):
            raise AssertionError("disabled Voice must not start dependency checks")

    monkeypatch.setattr(
        "modules.startup_diagnostics.RuntimeDependencyManager",
        UnexpectedManager,
    )

    result = _voice_check({"voice": {"enabled": False}})

    assert result["status"] == "disabled"
    assert "不会自动枚举" in result["detail"]


def test_enabled_voice_all_dependencies_ready():
    voice = _manager(
        settings={"voice": {"enabled": True}},
        modules={"faster_whisper", "ctranslate2", "edge_tts", "pygame"},
        microphone=(True, "Microphone detected"),
        playback=(True, "Output detected"),
        whisper=(True, "Cached"),
    ).check_voice(
        ffmpeg={"available": True, "detail": "FFmpeg ready"}
    )

    assert voice["ready"] is True
    assert voice["status"] == RuntimeStatus.READY.value
    assert all(item["status"] == RuntimeStatus.READY.value for item in voice["items"])


def test_voice_disabled_domain_is_not_enabled_and_does_not_block_ready_summary():
    report = _manager(
        settings={"voice": {"enabled": False}, "knowledge": {"enabled": True}},
        executable=r"C:\Program Files\Ollama\ollama.exe",
        available=True,
        models=READY_MODELS,
    ).check()

    assert report["domains"]["core"]["status"] == RuntimeStatus.READY.value
    assert report["domains"]["local_ai"]["status"] == RuntimeStatus.READY.value
    assert report["domains"]["knowledge"]["status"] == RuntimeStatus.READY.value
    assert report["domains"]["voice"]["status"] == RuntimeStatus.OPTIONAL.value
    assert report["status"] == RuntimeStatus.READY.value


def test_voice_enabled_with_missing_dependencies_makes_overall_not_ready():
    report = _manager(
        settings={"voice": {"enabled": True}, "knowledge": {"enabled": True}},
        executable=r"C:\Program Files\Ollama\ollama.exe",
        available=True,
        models=READY_MODELS,
    ).check()

    assert report["domains"]["core"]["status"] == RuntimeStatus.READY.value
    assert report["domains"]["local_ai"]["status"] == RuntimeStatus.READY.value
    assert report["domains"]["voice"]["status"] == RuntimeStatus.DEGRADED.value
    assert report["status"] == RuntimeStatus.DEGRADED.value


def test_voice_fully_ready_makes_voice_domain_and_overall_ready():
    report = _manager(
        settings={"voice": {"enabled": True}, "knowledge": {"enabled": True}},
        executable=r"C:\Program Files\Ollama\ollama.exe",
        ffmpeg=r"C:\Tools\ffmpeg.exe",
        available=True,
        models=READY_MODELS,
        modules={"faster_whisper", "ctranslate2", "edge_tts", "pygame"},
        microphone=(True, "Microphone detected"),
        playback=(True, "Output detected"),
        whisper=(True, "Cached"),
    ).check()

    assert report["domains"]["voice"]["status"] == RuntimeStatus.READY.value
    assert report["status"] == RuntimeStatus.READY.value


def test_dependency_center_stt_key_matches_runtime_report_contract():
    report = _manager(settings={"voice": {"enabled": False}}).check()

    assert "stt" in report["items_by_key"]
    source = (Path(__file__).resolve().parents[1] / "widgets" / "components" / "dependency_center.py").read_text(
        encoding="utf-8"
    )
    assert '"stt",' in source
    assert '"stt_runtime"' not in source


def test_enabled_voice_with_missing_ffmpeg_never_breaks_core_report():
    report = _manager(settings={"voice": {"enabled": True}}).check()

    assert report["core_ready"] is True
    assert report["items_by_key"]["aurora_core"]["status"] == RuntimeStatus.READY.value
    assert report["items_by_key"]["ffmpeg"]["status"] == RuntimeStatus.MISSING.value
    assert report["voice"]["status"] == RuntimeStatus.DEGRADED.value


def test_unified_voice_startup_gate_includes_ffmpeg_and_device_requirements():
    report = _manager(settings={"voice": {"enabled": True}}).check_voice_requirements()

    assert report["ready"] is False
    assert {item["key"] for item in report["missing"]} >= {
        "ffmpeg",
        "microphone",
        "stt",
        "whisper_model",
        "tts",
        "playback",
    }


def test_failing_optional_probes_are_contained():
    def fail():
        raise RuntimeError("device backend failed")

    manager = RuntimeDependencyManager(
        {"voice": {"enabled": True}},
        which=lambda _name: None,
        bundled_tool_finder=lambda _name: None,
        module_finder=_finder({"faster_whisper", "ctranslate2", "edge_tts", "pygame"}),
        ollama_api_probe=lambda _host, _timeout: (_ for _ in ()).throw(
            RuntimeError("API probe failed")
        ),
        microphone_probe=fail,
        playback_device_probe=fail,
        whisper_model_probe=lambda _model: (_ for _ in ()).throw(
            RuntimeError("cache failed")
        ),
        hardware_probe=lambda: (_ for _ in ()).throw(RuntimeError("WMI failed")),
        environment={},
    )

    report = manager.check()

    assert report["core_ready"] is True
    assert report["ollama"]["state"] == OllamaRuntimeState.NOT_INSTALLED.value
    assert report["voice"]["status"] == RuntimeStatus.DEGRADED.value
    assert report["hardware"]["vram_gb"] is None
    assert report["hardware"]["vram_status"] == "unknown"
    serialized = json.dumps(report)
    assert "device backend failed" not in serialized
    assert "cache failed" not in serialized
    assert "API probe failed" not in serialized
    assert "could not be checked" in serialized


@pytest.mark.parametrize(
    ("hardware", "tier", "model"),
    [
        (
            {"ram_gb": 8, "logical_cores": 4, "vram_gb": None, "disk_free_gb": 20},
            "Lightweight",
            "qwen3:4b",
        ),
        (
            {"ram_gb": 16, "logical_cores": 8, "vram_gb": None, "disk_free_gb": 50},
            "Balanced",
            "qwen3:8b",
        ),
        (
            {"ram_gb": 64, "logical_cores": 16, "vram_gb": 16, "disk_free_gb": 100},
            "Quality",
            "qwen3:14b",
        ),
    ],
)
def test_hardware_tier_recommendations(hardware, tier, model):
    recommendation = _manager().recommend_chat_model(hardware)

    assert recommendation["tier"] == tier
    assert recommendation["model"] == model
    assert recommendation["download_required"] is True
    assert recommendation["requires_user_confirmation"] is True


def test_unknown_vram_is_not_coerced_to_zero_or_used_for_quality():
    manager = _manager(
        hardware={
            "ram_gb": 64,
            "logical_cores": 16,
            "gpu": "Unknown GPU",
            "vram_gb": None,
            "disk_free_gb": 100,
        }
    )

    hardware = manager.inspect_hardware()
    recommendation = manager.recommend_chat_model(hardware)

    assert hardware["vram_gb"] is None
    assert hardware["vram_status"] == "unknown"
    assert recommendation["tier"] == "Balanced"
    assert any("not treated as 0" in warning for warning in recommendation["warnings"])


def test_low_disk_marks_recommended_download_unsafe():
    recommendation = _manager().recommend_chat_model(
        {"ram_gb": 8, "logical_cores": 4, "vram_gb": None, "disk_free_gb": 3}
    )

    assert recommendation["tier"] == "Lightweight"
    assert recommendation["can_download"] is False
    assert len(recommendation["warnings"]) >= 2


def test_existing_chat_model_is_preferred_without_download():
    recommendation = _manager().recommend_chat_model(
        {"ram_gb": 16, "logical_cores": 8, "vram_gb": None, "disk_free_gb": 50},
        READY_MODELS,
    )

    assert recommendation["model"] == "qwen3:8b"
    assert recommendation["action"] == "use_existing"
    assert recommendation["existing_model"] is True
    assert recommendation["download_required"] is False
    assert recommendation["requires_user_confirmation"] is False


def test_embedding_only_model_is_never_selected_for_chat():
    recommendation = _manager().recommend_chat_model(
        {"ram_gb": 16, "logical_cores": 8, "vram_gb": None, "disk_free_gb": 50},
        ["nomic-embed-text:latest"],
    )

    assert recommendation["model"] == "qwen3:8b"
    assert recommendation["existing_model"] is False
    assert recommendation["download_required"] is True


def test_check_never_installs_or_downloads_and_plain_mapping_is_not_persisted():
    calls = []

    def api(host, timeout):
        calls.append((host, timeout))
        return {"available": True, "models": READY_MODELS, "reason": "ready"}

    manager = RuntimeDependencyManager(
        {},
        which=lambda _name: None,
        bundled_tool_finder=lambda _name: None,
        module_finder=_finder(),
        ollama_api_probe=api,
        microphone_probe=lambda: (False, "missing"),
        playback_device_probe=lambda: (False, "missing"),
        whisper_model_probe=lambda _model: (False, "missing"),
        hardware_probe=lambda: {},
        environment={},
    )

    report = manager.check(timeout=0.25)

    assert calls == [("http://127.0.0.1:11434", 0.25)]
    assert report["side_effects"] == []
    assert not hasattr(manager, "install")
    assert not hasattr(manager, "download")


def test_ollama_default_windows_install_is_found_after_stale_path(tmp_path):
    executable = tmp_path / "Programs" / "Ollama" / "ollama.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()

    path, source = resolve_ollama_executable(
        "ollama serve",
        which=lambda _name: None,
        bundled_tool_finder=lambda _name: None,
        environment={"LOCALAPPDATA": str(tmp_path)},
    )

    assert path == str(executable.resolve())
    assert source == "Ollama Windows install"
