import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.first_run import empty_runtime_report
from modules.runtime_state import RuntimeState, mark_voice_unavailable
from modules.settings import Settings


ROOT = Path(__file__).resolve().parents[1]


def report(ready, enabled=True):
    value = empty_runtime_report()
    items = {key: {"key": key, "status": "Ready" if ready else "Missing",
                   "available": ready, "data": {"runtime_available": ready}}
             for key in ("stt", "tts", "tts_service", "playback", "whisper_model", "ffmpeg", "microphone")}
    voice = {"enabled": enabled, "ready": ready and enabled,
             "status": "Optional" if not enabled else "Ready" if ready else "Degraded"}
    value.update(voice=voice, items_by_key=items, items=list(items.values()),
                 domains={"voice": {"status": voice["status"], "available": voice["ready"], "data": {"enabled": enabled}}})
    return value


@pytest.fixture
def store(tmp_path):
    settings = Settings.__new__(Settings)
    settings.config_dir = tmp_path
    settings.config_file = tmp_path / "settings.json"
    settings.data = {"voice": {"enabled": True}, "language": "zh_CN"}
    return settings


class Probe:
    def __init__(self, settings):
        self.settings = settings
        self.ready = False
        self.calls = []

    def check(self, **kwargs):
        self.calls.append(kwargs)
        return report(self.ready, self.settings.get("voice.enabled", False))


def make_state(store, **kwargs):
    probe = Probe(store)
    state = RuntimeState(store, manager=probe, dispatch=lambda fn: fn(),
                         start_worker=lambda fn: fn(), **kwargs)
    return state, probe


def test_missing_check_ready_restart_ready_no_restart_loop(store):
    state, probe = make_state(store)
    seen = []
    state.subscribe(lambda snap: seen.append(snap))
    state.refresh()
    assert seen[-1].report["voice"]["ready"] is False
    probe.ready = True
    state.refresh()
    assert seen[-1].report["voice"]["ready"] is True
    assert not seen[-1].restart_required
    state.close()
    next_process, probe2 = make_state(store)
    probe2.ready = True
    next_process.refresh()
    assert next_process.snapshot.report["voice"]["ready"] is True
    assert not next_process.snapshot.restart_required


def test_only_explicit_native_restart_persists_then_clears_after_process_change(store):
    state, probe = make_state(store)
    probe.ready = True
    state.require_native_restart("test native DLL was already loaded")
    saved = json.loads(store.config_file.read_text(encoding="utf-8"))
    assert saved["runtime"]["restart_required"] is True
    state.refresh()
    assert state.snapshot.restart_required
    restarted, new_probe = make_state(store)
    new_probe.ready = True
    restarted.refresh()
    assert not restarted.snapshot.restart_required
    assert store.get("runtime.restart_reason") == ""
    assert not json.loads(store.config_file.read_text(encoding="utf-8"))["runtime"]["restart_required"]


def test_restart_is_not_cleared_when_native_components_still_missing(store):
    state, _ = make_state(store)
    state.require_native_restart("native loader")
    restarted, _ = make_state(store)
    restarted.refresh()
    assert restarted.snapshot.restart_required


def test_runtime_snapshots_are_isolated_between_observers(store):
    state, probe = make_state(store)
    probe.ready = True
    state.subscribe(lambda snap: snap.report.update(voice={"ready": False}))
    state.refresh()
    assert state.snapshot.report["voice"]["ready"]


def test_stale_probe_does_not_publish_or_overwrite_new_settings(store):
    work, dispatch = [], []
    probe = Probe(store)
    state = RuntimeState(store, manager=probe, dispatch=dispatch.append, start_worker=work.append)
    seen = []
    state.subscribe(lambda snap: seen.append(snap))
    state.refresh(reevaluate=True)
    store.set("voice.enabled", False)
    state.refresh()
    work.pop(0)()
    dispatch.pop(0)()
    assert state.snapshot.revision == 0
    assert len(work) == 1
    work.pop(0)()
    dispatch.pop(0)()
    assert not state.snapshot.report["voice"]["enabled"]
    assert [call["reevaluate_models"] for call in probe.calls] == [True, True]
    assert all(call["timeout"] == 5 for call in probe.calls)
    assert len([snap for snap in seen if snap.revision]) == 1


def test_old_auto_model_selection_does_not_overwrite_manual_action(store):
    work, dispatch = [], []
    probe = Probe(store)
    def check(**kwargs):
        probe.settings.update_many({"chat_model": "old-auto"})
        return report(True)
    probe.check = check
    state = RuntimeState(store, manager=probe, dispatch=dispatch.append, start_worker=work.append)
    state.refresh()
    work.pop(0)()
    store.set("chat_model", "new-manual")
    state.refresh()
    dispatch.pop(0)()
    assert store.get("chat_model") == "new-manual"
    state.close()


def test_unsubscribe_and_shutdown_drop_late_notifications(store):
    work, dispatch, calls = [], [], []
    state = RuntimeState(store, manager=Probe(store), dispatch=dispatch.append, start_worker=work.append)
    unsubscribe = state.subscribe(calls.append)
    unsubscribe()
    state.refresh()
    work.pop(0)()
    state.close()
    dispatch.pop(0)()
    assert len(calls) == 1


def test_failed_probe_finishes_and_next_check_recovers(store):
    state, probe = make_state(store)
    good_check = probe.check
    probe.check = lambda **_: (_ for _ in ()).throw(RuntimeError("driver"))
    state.refresh()
    assert state.snapshot.error and not state.snapshot.checking
    probe.check, probe.ready = good_check, True
    state.refresh()
    assert not state.snapshot.error and state.snapshot.report["voice"]["ready"]


def production_voice_gate(store):
    # Compile the actual production boundary, not a parallel fake implementation.
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "apply_runtime_voice")
    calls = []
    runtime = SimpleNamespace(close=lambda: calls.append("close") or True)
    namespace = dict(settings=store, voice_runtime=None, voice_runtime_signature=None,
                     active_chat_page=SimpleNamespace(attach_voice_runtime=lambda value, **kw: calls.append((value, kw))),
                     mark_voice_unavailable=mark_voice_unavailable,
                     create_application_voice_runtime=lambda value: calls.append("create") or runtime)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "main.py", "exec"), namespace)
    return namespace, runtime, calls


def test_production_voice_gate_hot_creates_once_reconfigures_and_disables(store):
    scope, runtime, calls = production_voice_gate(store)
    state, probe = make_state(store, prepare_voice=scope["apply_runtime_voice"])
    state.refresh()
    assert "create" not in calls
    probe.ready = True
    state.refresh()
    assert calls.count("create") == 1
    assert calls[-1] == (runtime, {"available": True})
    state.refresh()
    assert calls.count("create") == 1
    store.set("voice.recorder.ffmpeg_path", "new-path")
    state.refresh()
    assert calls.count("close") == 1 and calls.count("create") == 2
    store.set("voice.enabled", False)
    state.refresh()
    assert calls.count("close") == 2
    assert calls[-1] == (None, {"available": False})


def test_production_voice_factory_failure_cannot_publish_ready(store):
    scope, _, calls = production_voice_gate(store)
    scope["create_application_voice_runtime"] = lambda value: None
    state, probe = make_state(store, prepare_voice=scope["apply_runtime_voice"])
    probe.ready = True
    state.refresh()
    assert not state.snapshot.report["voice"]["ready"]
    assert state.snapshot.report["domains"]["voice"]["status"] == "Degraded"
    assert calls[-1][1] == {"available": False}


def test_production_does_not_create_second_audio_owner_while_old_stopping(store):
    scope, runtime, calls = production_voice_gate(store)
    scope["voice_runtime"] = runtime
    runtime.close = lambda: False
    result = report(True)
    scope["apply_runtime_voice"](result)
    assert "create" not in calls
    assert result["voice"]["initialization_error"] == "previous_session_stopping"


def test_production_navigation_has_no_complete_settings_route():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "SettingsWindow(" not in source
    assert "RuntimeDependencyManager(" not in source
    for path in ("widgets/pages/settings_page.py", "widgets/voice_setup_wizard.py", "widgets/first_run_wizard.py", "widgets/components/dependency_center.py"):
        source = (ROOT / path).read_text(encoding="utf-8")
        assert "RuntimeDependencyManager(" not in source
        assert ".subscribe(self._on_snapshot)" in source
        assert "self._unsubscribe()" in source
    source = (ROOT / "widgets/pages/settings_page.py").read_text(encoding="utf-8")
    assert "developer_open_full_settings" not in source
    assert "open_settings_editor" not in source


@pytest.mark.parametrize("language, word", [("zh_CN", "重启"), ("en_US", "restart")])
def test_hot_setup_text_never_asks_for_restart(language, word):
    locale = json.loads((ROOT / "locales" / f"{language}.json").read_text(encoding="utf-8"))
    for key in ("voice_setup_intro", "voice_setup_ready", "voice_dependencies_ready_after_save"):
        assert word not in locale[key].lower()
    assert word in locale["runtime_native_restart"].lower()
