import inspect
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules import voice_models
from modules.dependency_actions import download_whisper_model, select_whisper_model
from modules.runtime_dependencies import RuntimeDependencyManager
from modules.runtime_display import localized_runtime_item
from widgets.voice_setup_wizard import voice_setup_plan


def manager(**kwargs):
    defaults = dict(
        settings={"voice": {"enabled": True}},
        which=lambda _name: "ffmpeg.exe",
        bundled_tool_finder=lambda _name: None,
        module_finder=lambda _name: object(),
        module_importer=lambda _name: object(),
        microphone_probe=lambda: (True, "Test microphone"),
        playback_device_probe=lambda: (True, "Test output"),
        whisper_model_probe=lambda _name: (True, "Test model"),
        tts_service_probe=lambda _timeout: (True, "Test service"),
        ffmpeg_probe=lambda _path: True,
    )
    defaults.update(kwargs)
    return RuntimeDependencyManager(**defaults)


def report(checker):
    data = checker.check_voice_requirements()
    return {"voice": data["voice"], "items_by_key": {i["key"]: i for i in data["items"]}}


def test_full_runtime_plan_only_contains_external_missing_items():
    data = report(manager(whisper_model_probe=lambda _name: (False, "Missing"), ffmpeg_probe=lambda _path: False, microphone_probe=lambda: (False, "Missing")))
    assert voice_setup_plan(data) == ["whisper_model", "ffmpeg", "microphone"]
    assert all(data["items_by_key"][key]["status"] == "Ready" for key in ("stt", "tts", "playback"))


def test_core_directs_user_to_full_build_not_model_download():
    data = report(manager(module_finder=lambda _name: None))
    assert "full_build" in voice_setup_plan(data)
    assert "whisper_model" not in voice_setup_plan(data)
    assert data["voice"]["ready"] is False


def test_dll_load_failure_is_not_runtime_ready():
    def broken(name):
        if name == "ctranslate2":
            raise OSError("native DLL cannot load")
    data = report(manager(module_importer=broken))
    assert data["items_by_key"]["stt"]["status"] == "Missing"
    assert not data["voice"]["ready"]
    assert "native DLL" not in json.dumps(data)


def test_offline_tts_does_not_mislabel_installed_runtime():
    data = report(manager(tts_service_probe=lambda _timeout: (False, "Network unavailable")))
    assert data["items_by_key"]["tts"]["status"] == "Ready"
    assert data["items_by_key"]["tts_service"]["status"] == "Degraded"
    assert not data["voice"]["ready"]
    assert voice_setup_plan(data) == ["tts_service"]


def test_production_startup_classifies_service_outage_separately():
    from modules.experience.voice.integration import create_optional_voice_runtime
    runtime, diagnostics = create_optional_voice_runtime(
        {"voice": {"enabled": True}},
        lambda: pytest.fail("Service unavailable must not start Voice"),
        dependency_checker=lambda _settings: manager(tts_service_probe=lambda _timeout: (False, "Offline")).check_voice_requirements(),
    )
    assert runtime is None
    assert diagnostics["reason"] == "tts_service_unavailable"
    assert diagnostics["metrics"]["tts_runtime_installed"] is True


def test_voice_disabled_has_no_native_network_or_device_probes():
    def forbidden(*_args):
        pytest.fail("Voice Off triggered an active probe")
    data = report(manager(settings={"voice": {"enabled": False}}, module_importer=forbidden, tts_service_probe=forbidden, ffmpeg_probe=forbidden, microphone_probe=forbidden, playback_device_probe=forbidden, whisper_model_probe=forbidden))
    assert voice_setup_plan(data) == []
    assert data["voice"]["status"] == "Optional"


def test_ready_voice_has_no_install_actions():
    data = report(manager())
    assert data["voice"]["ready"]
    assert voice_setup_plan(data) == []


def test_broken_ffmpeg_file_is_not_ready():
    data = report(manager(ffmpeg_probe=lambda _path: False))
    assert data["items_by_key"]["ffmpeg"]["available"] is False
    assert not data["voice"]["ready"]


def write_model(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "model.bin").write_bytes(b"model" * 1024)
    (path / "config.json").write_text("{}", encoding="utf-8")
    (path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (path / "vocabulary.txt").write_text("test\n", encoding="utf-8")
    # Stand in for files whose content hashes were supplied by Hugging Face.
    metadata = path / ".cache/huggingface/download"
    metadata.mkdir(parents=True, exist_ok=True)
    for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
        digest = hashlib.sha256((path / name).read_bytes()).hexdigest()
        (metadata / (name + ".metadata")).write_text(f"revision\n{digest}\n0\n", encoding="utf-8")


def test_empty_or_partial_model_never_ready(tmp_path):
    assert not voice_models.valid_model_directory(tmp_path)
    (tmp_path / "model.bin").write_bytes(b"partial")
    assert not voice_models.valid_model_directory(tmp_path)
    write_model(tmp_path)
    assert voice_models.valid_model_directory(tmp_path)
    (tmp_path / "tokenizer.json").write_text("broken", encoding="utf-8")
    assert not voice_models.valid_model_directory(tmp_path)


def test_managed_model_is_shared_by_diagnostics_and_stt(monkeypatch, tmp_path):
    monkeypatch.setattr(voice_models, "USER_DATA_DIR", tmp_path)
    path = voice_models.managed_model_path("tiny")
    write_model(path)
    assert voice_models.local_model_path("tiny") == path
    from modules.experience.voice.providers.faster_whisper import FasterWhisperProvider
    calls = []
    import sys
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=lambda *a, **kw: calls.append((a, kw))))
    FasterWhisperProvider._default_model_loader("tiny", "cpu", "int8")
    assert calls == [((str(path),), {"device": "cpu", "compute_type": "int8", "local_files_only": True})]


def test_model_selection_persists_user_chosen_tier():
    settings = {}
    select_whisper_model(settings, "tiny")
    assert settings["voice"]["stt"]["model_size"] == "tiny"
    with pytest.raises(ValueError):
        select_whisper_model(settings, "unapproved-model")


def test_windows_download_path_covers_long_hub_temporary_filenames(tmp_path):
    import os
    value = voice_models.model_download_directory(tmp_path / "models/whisper/tiny.download")
    if os.name == "nt":
        assert value.startswith("\\\\?\\")
    else:
        assert value == str((tmp_path / "models/whisper/tiny.download").resolve())


def test_download_consent_is_required_before_import_or_network():
    calls = []
    result = download_whisper_model("tiny", confirmed=False, downloader=lambda name: calls.append(name))
    assert result.status == "confirmation_required"
    assert calls == []


def test_interrupted_model_download_is_not_published(monkeypatch, tmp_path):
    monkeypatch.setattr(voice_models, "USER_DATA_DIR", tmp_path)
    import sys
    def broken(_name, *, output_dir):
        Path(output_dir).mkdir(parents=True)
        (Path(output_dir) / "model.bin").write_bytes(b"partial")
        raise OSError("network interrupted")
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", SimpleNamespace(download_model=broken))
    result = download_whisper_model("tiny", confirmed=True)
    assert not result.ok
    assert not voice_models.managed_model_path("tiny").exists()
    assert voice_models.local_model_path("tiny") is None


def test_successful_model_download_publishes_complete_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(voice_models, "USER_DATA_DIR", tmp_path)
    import sys
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", SimpleNamespace(download_model=lambda _name, output_dir: write_model(Path(output_dir))))
    assert download_whisper_model("tiny", confirmed=True).ok
    assert voice_models.valid_model_directory(voice_models.managed_model_path("tiny"))
    assert (voice_models.managed_model_path("tiny") / "aurora-model-integrity.json").is_file()


def test_junk_model_without_verified_hashes_is_not_ready(tmp_path, monkeypatch):
    write_model(tmp_path)
    for path in (tmp_path / ".cache/huggingface/download").glob("*.metadata"):
        path.unlink()
    def invalid_model(_path):
        raise ValueError("invalid CTranslate2 model")
    monkeypatch.setattr(voice_models, "_load_legacy_model", invalid_model)
    assert not voice_models.valid_model_directory(tmp_path)


def test_legacy_model_load_is_cached_until_files_change(tmp_path, monkeypatch):
    write_model(tmp_path)
    for path in (tmp_path / ".cache/huggingface/download").glob("*.metadata"):
        path.unlink()
    calls = []
    monkeypatch.setattr(voice_models, "_load_legacy_model", lambda path: calls.append(path))
    assert voice_models.valid_model_directory(tmp_path)
    assert voice_models.valid_model_directory(tmp_path)
    assert len(calls) == 1
    assert not (tmp_path / "aurora-model-integrity.json").exists()
    (tmp_path / "model.bin").write_bytes(b"changed" * 1024)
    assert voice_models.valid_model_directory(tmp_path)
    assert len(calls) == 2


def test_missing_vocabulary_is_not_ready(tmp_path):
    write_model(tmp_path)
    (tmp_path / "vocabulary.txt").unlink()
    assert not voice_models.valid_model_directory(tmp_path)


def test_git_blob_hub_metadata_is_verified(tmp_path):
    write_model(tmp_path)
    data = (tmp_path / "config.json").read_bytes()
    digest = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    metadata = tmp_path / ".cache/huggingface/download/config.json.metadata"
    metadata.write_text(f"revision\n{digest}\n0\n", encoding="utf-8")
    assert voice_models.valid_model_directory(tmp_path)
    (tmp_path / "config.json").write_text('{"changed":true}', encoding="utf-8")
    assert not voice_models.valid_model_directory(tmp_path)


def test_corrupt_published_model_is_redownloaded_not_skipped(monkeypatch, tmp_path):
    monkeypatch.setattr(voice_models, "USER_DATA_DIR", tmp_path)
    path = voice_models.managed_model_path("tiny")
    write_model(path)
    voice_models.publish_model_integrity(path)
    assert voice_models.valid_model_directory(path)
    (path / "model.bin").write_bytes(b"broken" * 1024)
    assert not voice_models.valid_model_directory(path)
    calls = []
    def download(name, output_dir):
        calls.append(name)
        write_model(Path(output_dir))
    import sys
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", SimpleNamespace(download_model=download))
    assert download_whisper_model("tiny", confirmed=True).ok
    assert calls == ["tiny"]
    assert voice_models.valid_model_directory(path)
    assert list(path.parent.glob("tiny.invalid-*"))


def test_corrupt_complete_staging_does_not_poison_retry(monkeypatch, tmp_path):
    monkeypatch.setattr(voice_models, "USER_DATA_DIR", tmp_path)
    staging = voice_models.managed_model_path("tiny").with_name("tiny.download")
    write_model(staging)
    (staging / "model.bin").write_bytes(b"broken" * 1024)
    def download(_name, output_dir):
        assert not Path(output_dir).exists()
        write_model(Path(output_dir))
    import sys
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", SimpleNamespace(download_model=download))
    assert download_whisper_model("tiny", confirmed=True).ok
    assert list(staging.parent.glob("tiny.download.invalid-*"))


def test_integrity_marker_write_failure_does_not_publish(monkeypatch, tmp_path):
    monkeypatch.setattr(voice_models, "USER_DATA_DIR", tmp_path)
    import sys
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", SimpleNamespace(download_model=lambda _name, output_dir: write_model(Path(output_dir))))
    def fail_replace(_source, _target):
        raise OSError("simulated disk error")
    monkeypatch.setattr(voice_models.os, "replace", fail_replace)
    assert not download_whisper_model("tiny", confirmed=True).ok
    assert not voice_models.managed_model_path("tiny").exists()


@pytest.mark.parametrize("device,compute,expected", [("auto", "auto", ("cpu", "int8")), ("auto", "float32", ("cpu", "float32")), ("cuda", "auto", ("cuda", "auto")), ("cpu", "auto", ("cpu", "auto"))])
def test_frozen_stt_auto_uses_supported_cpu_without_overriding_explicit_choices(monkeypatch, device, compute, expected):
    import sys
    from modules.experience.voice.integration import _create_stt
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    provider = _create_stt({"voice": {"stt": {"device": device, "compute_type": compute}}})
    assert (provider.device, provider.compute_type) == expected


def test_source_stt_keeps_existing_auto_selection(monkeypatch):
    import sys
    from modules.experience.voice.integration import _create_stt
    monkeypatch.delattr(sys, "frozen", raising=False)
    provider = _create_stt({})
    assert (provider.device, provider.compute_type) == ("auto", "auto")


def test_frozen_diagnostic_uses_production_stt_factory(monkeypatch, tmp_path):
    from modules import voice_runtime_check, runtime_dependencies
    from modules.experience.voice import integration
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"test audio")
    output = tmp_path / "report.json"
    calls = []
    provider = SimpleNamespace(transcribe=lambda audio, **kwargs: SimpleNamespace(text="test", diagnostics={"success": True}))
    monkeypatch.setattr(integration, "_create_stt", lambda settings: calls.append(settings) or provider)
    monkeypatch.setattr(runtime_dependencies, "RuntimeDependencyManager", lambda settings: SimpleNamespace(check_voice_requirements=lambda **kwargs: {"ready": True}))
    monkeypatch.setattr(voice_runtime_check.importlib, "import_module", lambda name: SimpleNamespace(__file__=str(audio)))
    monkeypatch.setattr(voice_runtime_check.metadata, "version", lambda name: "test")
    assert voice_runtime_check.main(["--voice-runtime-check", str(output), "--stt-audio", str(audio), "--model", "small"]) == 0
    assert calls[0]["voice"]["stt"]["model_size"] == "small"
    assert "device" not in calls[0]["voice"]["stt"]
    assert json.loads(output.read_text(encoding="utf-8"))["stt"]["text"] == "test"


def test_chinese_voice_plan_and_tts_details_are_translated():
    root = Path(__file__).resolve().parents[1]
    en = json.loads((root / "locales/en_US.json").read_text(encoding="utf-8"))
    zh = json.loads((root / "locales/zh_CN.json").read_text(encoding="utf-8"))
    assert set(en) == set(zh)
    for action in ("full_build", "whisper_model", "ffmpeg", "microphone", "tts_service", "playback"):
        assert any("\u4e00" <= c <= "\u9fff" for c in zh[f"voice_setup_plan_{action}"])
    item = localized_runtime_item({"key": "tts_service", "status": "Degraded", "detail": "RAW EXCEPTION"}, zh.__getitem__)
    assert "RAW EXCEPTION" not in item["detail"]
    assert "网络" in item["detail"]


def test_runtime_diagnostic_entry_remains_after_instance_gate_before_services():
    root = Path(__file__).resolve().parents[1]
    source = (root / "main.py").read_text(encoding="utf-8")
    assert source.index("single_instance_guard = enforce_single_instance()") < source.index('"--voice-runtime-check"') < source.index("import customtkinter")
    from modules import voice_runtime_check
    source = inspect.getsource(voice_runtime_check)
    assert "pip install" not in source
    assert "--download-whisper" in source


def test_settings_snapshot_refreshes_after_dialog_close():
    from widgets.pages.settings_page import SettingsPage
    from widgets.voice_setup_wizard import VoiceSetupWizard
    calls = []
    page = SimpleNamespace(runtime_state=SimpleNamespace(refresh=lambda: calls.append("refresh")))
    SettingsPage.refresh_after_settings_change(page)
    assert calls == ["refresh"]
    source = inspect.getsource(VoiceSetupWizard.destroy)
    assert "self.runtime_state.refresh()" in source
    assert "self.on_close()" in source
