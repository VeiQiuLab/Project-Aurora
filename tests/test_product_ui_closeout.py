import inspect
import json
from pathlib import Path
from types import SimpleNamespace

from widgets.app_shell import AppShell
from widgets.components.dependency_center import (
    DependencyCenter,
    _DOMAIN_ITEMS,
    runtime_domain_status_text,
)
from widgets.pages.settings_page import SettingsPage
from widgets.voice_setup_wizard import VOICE_SETUP_KEYS, voice_setup_state


ROOT = Path(__file__).resolve().parents[1]


def translate(key):
    return {
        "runtime_status_ready": "Ready",
        "runtime_status_not_enabled": "Not enabled",
        "runtime_status_not_configured": "Not configured",
        "runtime_status_needs_attention": "Needs attention",
        "runtime_status_needs_configuration": "Needs configuration",
    }.get(key, key)


def test_runtime_default_view_is_three_product_domains_with_lightweight_core():
    assert _DOMAIN_ITEMS == ("local_ai", "knowledge", "voice")
    source = inspect.getsource(DependencyCenter._build)
    assert "runtime_component_details" not in source
    assert "runtime_optional_features" not in source
    assert source.count("CTkOptionMenu") == 1


def test_compact_domain_status_vocabulary():
    assert runtime_domain_status_text("core", {"status": "Ready"}, translate) == "Ready"
    assert runtime_domain_status_text("knowledge", {"status": "Optional", "data": {}}, translate) == "Not configured"
    assert runtime_domain_status_text("voice", {"status": "Optional", "data": {"enabled": False}}, translate) == "Not enabled"
    assert runtime_domain_status_text("voice", {"status": "Degraded", "data": {"enabled": True}}, translate) == "Needs configuration"


def test_details_are_only_opened_by_explicit_diagnostics_action():
    build_source = inspect.getsource(DependencyCenter._build)
    diagnostics_source = inspect.getsource(DependencyCenter.show_diagnostics)
    assert "runtime_diagnostics" in build_source
    assert "show_runtime_details" in diagnostics_source


def test_voice_setup_checks_all_required_components():
    assert set(VOICE_SETUP_KEYS) == {"stt", "whisper_model", "tts", "tts_service", "playback", "ffmpeg", "microphone"}
    assert voice_setup_state({"voice": {"enabled": False, "ready": False}}) == "disabled"
    assert voice_setup_state({"voice": {"enabled": True, "ready": False}}) == "configure"
    assert voice_setup_state({"voice": {"enabled": True, "ready": True}}) == "ready"


def test_embedding_ready_does_not_offer_another_download():
    calls = []
    messages = []
    center = SimpleNamespace(
        report={
            "ollama": {"state": "Server Ready"},
            "recommendation": {"download_required": False},
            "items_by_key": {"embedding_model": {"status": "Ready"}},
        },
        download_embedding=lambda: calls.append("embedding"),
        t=lambda key: key,
        message=SimpleNamespace(configure=lambda **values: messages.append(values)),
    )

    DependencyCenter.install_or_download(center)

    assert calls == []
    assert messages[-1]["text"] == "runtime_chat_model_ready_action"


def test_voice_off_hides_device_and_setup_actions():
    source = inspect.getsource(SettingsPage._build_voice)
    assert "if not voice_enabled" in source
    assert "device_actions.pack_forget()" in source
    assert "if voice_enabled" in source


def voice_page(ready):
    from modules.runtime_state import RuntimeSnapshot
    changes, hidden, shown = [], [], []
    snapshot = RuntimeSnapshot(1, json.dumps({"voice": {"enabled": True, "ready": ready}}))
    page = SimpleNamespace(
        voice_setup_button=SimpleNamespace(configure=lambda **kw: changes.append(kw),
                                           pack_forget=lambda: hidden.append(True),
                                           pack=lambda **kw: shown.append(True)),
        voice_setup_status=SimpleNamespace(configure=lambda **kw: None),
        settings={"voice.enabled": True},
        runtime_state=SimpleNamespace(snapshot=snapshot),
        t=lambda key: key,
    )
    return page, changes, hidden, shown


def test_ready_voice_hides_setup_button():
    page, changes, hidden, shown = voice_page(True)
    SettingsPage._refresh_voice_setup_state(page)
    assert hidden == [True] and not shown


def test_incomplete_voice_enables_one_setup_action():
    page, changes, hidden, shown = voice_page(False)
    SettingsPage._refresh_voice_setup_state(page)
    assert changes == [{"text": "voice_setup_configure", "state": "normal"}]
    assert shown == [True] and not hidden


def test_sidebar_has_one_navigation_source_and_no_settings_heading():
    source = inspect.getsource(AppShell._build_settings_sidebar)
    assert "return_button" in source
    assert 'text=self.t("settings")' not in source
    assert SettingsPage.CATEGORIES == ["ai", "runtime", "voice", "qq", "appearance", "data", "developer"]


def test_voice_full_build_policy_is_pinned_and_runtime_install_disabled():
    policy = json.loads((ROOT / "config" / "voice_runtime_build.json").read_text(encoding="utf-8"))
    assert policy["runtime_package_install"] is False
    assert policy["codec_license_review_required"] is True
    assert all(value and value[0].isdigit() for value in policy["components"].values())
    spec = (ROOT / "Project Aurora.spec").read_text(encoding="utf-8")
    assert "AURORA_VOICE_CODEC_OVERLAY" in spec
    assert "voice_codec_lock.json" in spec
    assert "Codec overlay integrity mismatch" in spec
