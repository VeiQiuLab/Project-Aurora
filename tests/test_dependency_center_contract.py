from types import SimpleNamespace

from modules.runtime_dependencies import RuntimeDependencyManager
from widgets.components.dependency_center import DependencyCenter, _VISIBLE_ITEMS
from widgets.pages.chat_page import ChatPage
from widgets.pages.settings_page import SettingsPage
from widgets.settings_window import SettingsWindow


def test_dependency_center_visible_keys_exist_in_runtime_report():
    manager = RuntimeDependencyManager(
        {},
        which=lambda _name: None,
        bundled_tool_finder=lambda _name: None,
        module_finder=lambda _name: None,
        ollama_api_probe=lambda _host, _timeout: {
            "available": False,
            "models": [],
            "reason": "offline",
        },
        microphone_probe=lambda: (False, "missing"),
        playback_device_probe=lambda: (False, "missing"),
        whisper_model_probe=lambda _model: (False, "missing"),
        hardware_probe=lambda: {},
    )

    report = manager.check()

    assert set(_VISIBLE_ITEMS) <= set(report["items_by_key"])


def test_successful_dependency_download_selection_is_persisted():
    class Store:
        def __init__(self):
            self.calls = []

        def update_many(self, values, save=True):
            self.calls.append((values, save))

    store = Store()
    center = SimpleNamespace(settings=store)

    DependencyCenter._persist_model_selection(center, "Chat", "qwen3:8b")
    DependencyCenter._persist_model_selection(
        center, "Embedding", "nomic-embed-text"
    )

    assert store.calls == [
        (
            {
                "chat_model_mode": "manual",
                "chat_model": "qwen3:8b",
                "resolved_chat_model": "",
                "chat_model_resolution_reason": "manual_selection",
                "last_successful_chat_model": "qwen3:8b",
            },
            True,
        ),
        (
            {
                "embedding_model_mode": "manual",
                "embedding_model": "nomic-embed-text",
                "resolved_embedding_model": "",
                "embedding_model_resolution_reason": "manual_selection",
            },
            True,
        ),
    ]


def test_settings_voice_result_does_not_touch_a_closed_window():
    queued = []
    updated = []
    window = SimpleNamespace(
        _disposed=False,
        logger=None,
        after=lambda _delay, callback: queued.append(callback),
        winfo_exists=lambda: True,
    )

    SettingsWindow._after(window, lambda: updated.append(True))
    window._disposed = True
    queued[0]()

    assert updated == []


def test_whisper_download_is_blocked_until_stt_runtime_is_ready():
    messages = []
    center = SimpleNamespace(
        report={
            "voice": {"enabled": True},
            "items_by_key": {"stt": {"status": "Missing"}},
        },
        t=lambda key: {
            "runtime_install_stt_first": "Install the Faster-Whisper runtime first."
        }.get(key, key),
        message=SimpleNamespace(configure=lambda **values: messages.append(values)),
    )

    DependencyCenter.download_whisper(center)

    assert "Faster-Whisper runtime" in messages[-1]["text"]


def test_first_voice_enablement_reports_ffmpeg_from_unified_gate(monkeypatch):
    messages = []

    class Manager:
        def __init__(self, _settings):
            pass

        def check_voice_requirements(self):
            return {
                "ready": False,
                "items": [],
                "missing": [{"name": "FFmpeg", "available": False}],
            }

    class ImmediateThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr("widgets.settings_window.RuntimeDependencyManager", Manager)
    monkeypatch.setattr("widgets.settings_window.threading.Thread", ImmediateThread)
    window = SimpleNamespace(
        settings={},
        logger=None,
        t=lambda key: {
            "voice_dependencies_checking_after_save": "Checking Voice dependencies.",
            "voice_dependencies_missing_after_save": "Voice still needs: {components}.",
        }.get(key, key),
        result_label=SimpleNamespace(configure=lambda **values: messages.append(values)),
        _after=lambda callback: callback(),
    )

    SettingsWindow._check_first_voice_enablement(window)

    assert "FFmpeg" in messages[-1]["text"]


def test_voice_device_status_hides_dshow_exception_text(monkeypatch):
    statuses = []

    def fail_enumeration(_path):
        from modules.experience.audio.device_discovery import AudioDeviceDiscoveryError

        raise AudioDeviceDiscoveryError("DirectShow HRESULT 0x80070005")

    monkeypatch.setattr(
        "widgets.pages.settings_page.enumerate_dshow_audio_devices",
        fail_enumeration,
    )
    page = SimpleNamespace(
        settings={"voice": {"recorder": {"ffmpeg_path": "ffmpeg"}}},
        t=lambda key: {
            "voice_device_not_found": "未检测到可用麦克风。请确认 FFmpeg 后重试。"
        }.get(key, key),
        _set_voice_device_status=lambda text, status: statuses.append((text, status)),
    )

    SettingsPage._choose_voice_input_device(page)

    assert statuses[-1][1] == "error"
    assert "DirectShow" not in statuses[-1][0]
    assert "FFmpeg" in statuses[-1][0]


def test_chat_page_prefers_unified_api_model_catalog(monkeypatch):
    received = []
    fallback_calls = []

    class Manager:
        def __init__(self, _settings):
            pass

        def check_models(self, timeout=1.0):
            return {
                "ollama": {
                    "models": {
                        "all": [{"name": "qwen3:4b", "capability": "Chat Supported"}]
                    }
                }
            }

    monkeypatch.setattr("widgets.pages.chat_page.RuntimeDependencyManager", Manager)
    page = SimpleNamespace(
        settings={},
        logger=SimpleNamespace(info=lambda *_args: None, error=lambda *_args: None),
        model_records_provider=lambda: fallback_calls.append(True),
        after=lambda _delay, callback: callback(),
        update_models=lambda records: received.extend(records),
    )

    ChatPage.load_models(page)

    assert [item["name"] for item in received] == ["qwen3:4b"]
    assert fallback_calls == []


def test_chat_page_user_picker_pins_manual_selection():
    class Store:
        def __init__(self):
            self.values = {}

        def update_many(self, values, save=True):
            self.values.update(values)

    store = Store()
    page = SimpleNamespace(
        t=lambda key: key,
        model_capability_provider=lambda _model: "Chat Supported",
        selected_model={"name": ""},
        settings=store,
        set_model_display=lambda *_args: None,
        set_status=lambda *_args: None,
        logger=SimpleNamespace(info=lambda *_args: None),
    )

    ChatPage.select_model(page, "qwen3:4b")

    assert store.values["chat_model_mode"] == "manual"
    assert store.values["chat_model"] == "qwen3:4b"


def test_settings_model_picker_preserves_manual_value_while_ollama_is_offline():
    values, selected = SettingsWindow._model_picker_values(
        [],
        "qwen3:4b",
        "No installed Chat models",
    )

    assert values == ["qwen3:4b"]
    assert selected == "qwen3:4b"
