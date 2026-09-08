"""Real Tk widget contracts; no network, downloads or audio capture."""

import json
from pathlib import Path
from types import SimpleNamespace

import customtkinter as ctk
import pytest

from modules.runtime_state import RuntimeState
from modules.settings import Settings
from widgets.pages.settings_page import SettingsPage
from widgets.voice_setup_wizard import VoiceSetupWizard
from test_runtime_snapshot import Probe


@pytest.fixture(scope="module")
def tk_root():
    # Match production: one Tcl/Tk interpreter, isolated widgets per case.
    # Repeated interpreter teardown can fail to reopen Tcl files on Windows.
    root = ctk.CTk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def ui(tmp_path, tk_root):
    root = tk_root
    store = Settings.__new__(Settings)
    store.config_dir, store.config_file = tmp_path, tmp_path / "settings.json"
    store.data = {"voice": {"enabled": True}, "language": "zh_CN"}
    probe = Probe(store)
    state = RuntimeState(store, manager=probe, dispatch=lambda fn: fn(), start_worker=lambda fn: fn())
    locale = json.loads((Path(__file__).resolve().parents[1] / "locales/zh_CN.json").read_text(encoding="utf-8"))
    translate = lambda key: locale.get(key, key)
    page = SettingsPage(root, settings=store, runtime_state=state, translate=translate, text={})
    state.refresh()
    yield root, page, state, probe, translate
    state.close()
    for child in list(root.winfo_children()):
        child.destroy()
    root.update_idletasks()


@pytest.mark.parametrize("source", ["runtime", "voice"])
def test_wizard_completes_to_source_and_live_snapshot_updates_without_navigation(ui, source):
    root, page, state, probe, translate = ui
    page.show_category(source)
    root.update_idletasks()
    center = page.active_panel
    wizard = VoiceSetupWizard(page, settings=page.settings, runtime_state=state, translate=translate)
    assert wizard.runtime_state is page.runtime_state
    assert page.current_category == source
    probe.ready = True
    wizard.recheck()
    root.update_idletasks()
    if source == "voice":
        assert page.voice_setup_status.cget("text") == "就绪"
    else:
        assert center.domain_rows["voice"][0].cget("text") == "就绪"
    assert "重启" not in wizard.notice.cget("text")
    wizard.destroy()
    assert page.current_category == source
    assert state.snapshot.report["voice"]["ready"]


@pytest.mark.parametrize("source", ["runtime", "voice"])
def test_cancel_returns_to_same_destination(ui, source):
    root, page, state, probe, translate = ui
    page.show_category(source)
    wizard = VoiceSetupWizard(page, settings=page.settings, runtime_state=state, translate=translate)
    wizard.destroy()
    assert page.current_category == source
    assert not state.snapshot.report["voice"]["ready"]


def test_runtime_and_voice_instances_observe_same_result(ui):
    root, page, state, probe, translate = ui
    page.show_category("runtime")
    second_page = SettingsPage(root, settings=page.settings, runtime_state=state, translate=translate, text={})
    second_page.show_category("voice")
    probe.ready = True
    state.refresh()
    assert page.active_panel.domain_rows["voice"][0].cget("text") == second_page.voice_setup_status.cget("text") == "就绪"
    probe.ready = False
    state.refresh()
    assert page.active_panel.domain_rows["voice"][0].cget("text") == second_page.voice_setup_status.cget("text") == "需要配置"
    assert page.active_panel.voice_setup_button.cget("text") == "修复语音"
    second_page.destroy()


def test_each_category_owns_new_scroll_canvas_without_global_settings(ui):
    root, page, state, probe, translate = ui
    canvases = []
    for category in page.CATEGORIES:
        page.show_category(category)
        root.update_idletasks()
        canvases.append(page.body._parent_canvas)
        assert page.current_category == category
    assert len(set(map(id, canvases))) == len(page.CATEGORIES)


def test_runtime_has_one_voice_summary_and_no_low_level_default_labels(ui):
    root, page, state, probe, translate = ui
    page.show_category("runtime")
    labels = []
    def visit(widget):
        if isinstance(widget, ctk.CTkLabel):
            labels.append(widget.cget("text"))
        for child in widget.winfo_children():
            visit(child)
    visit(page.active_panel)
    assert labels.count("语音") == 1
    assert set(page.active_panel.domain_rows) == {"local_ai", "knowledge", "voice"}
    assert not any(token in text for text in labels for token in ("DirectShow", "STT", "CTranslate2", "ffmpeg.exe"))


def test_toggle_voice_off_hot_notifies_and_hides_setup(ui):
    root, page, state, probe, translate = ui
    page.show_category("voice")
    page.voice_enabled_var.set(False)
    page._toggle_voice()
    root.update_idletasks()
    assert page.voice_setup_status.cget("text") == "未启用"
    assert not page.voice_setup_button.winfo_manager()
    assert not state.snapshot.report["voice"]["enabled"]


def test_open_details_tracks_revisions_and_unsubscribes_when_closed(ui):
    root, page, state, probe, translate = ui
    window = page._show_runtime_details()
    box = next(child for child in window.winfo_children() if isinstance(child, ctk.CTkTextbox))
    before = len(state._observers)
    probe.ready = True
    state.refresh()
    payload = json.loads(box.get("1.0", "end"))
    assert payload["revision"] == state.snapshot.revision
    assert payload["voice"]["ready"] is True
    assert "stt" in payload["items_by_key"]
    window.destroy()
    assert len(state._observers) == before - 1


def test_wizard_does_not_discard_download_completion_when_closed(ui):
    root, page, state, probe, translate = ui
    wizard = VoiceSetupWizard(page, settings=page.settings, runtime_state=state, translate=translate)
    wizard._downloading = True
    wizard.destroy()
    assert not wizard._disposed
    assert wizard.winfo_exists()
    assert wizard.notice.cget("text") == translate("voice_setup_wait_download")
    wizard._downloading = False
    wizard.destroy()
    assert wizard._disposed
