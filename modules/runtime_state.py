"""One event-driven runtime snapshot per application; widgets never probe."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from threading import Thread
from uuid import uuid4

from modules.first_run import empty_runtime_report
from modules.runtime_dependencies import RuntimeDependencyManager


@dataclass(frozen=True)
class RuntimeSnapshot:
    revision: int
    payload: str
    checking: bool = False
    error: bool = False
    restart_required: bool = False
    restart_reason: str = ""

    @property
    def report(self):
        # Observers cannot accidentally change another page's snapshot.
        return json.loads(self.payload)


class _ProbeSettings:
    """Buffer automatic model selections until a non-stale probe is accepted."""

    def __init__(self, settings):
        self.data = copy.deepcopy(settings.data)
        self.updates = {}

    def get(self, key, default=None):
        value = self.data
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    def set(self, key, value):
        self.update_many({key: value})

    def update_many(self, values, save=True):
        for key, value in values.items():
            target = self.data
            parts = key.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
        self.updates.update(values)


class RuntimeState:
    """Serialized probes, dispatched notifications, no periodic polling.

    All public methods and callbacks run on the UI thread. Only the probe
    runs in a worker. An action during a probe invalidates its result and
    queues one latest-settings probe, including any re-evaluation request.
    """

    def __init__(self, settings, *, dispatch, manager=None, prepare_voice=None,
                 logger=None, start_worker=None):
        self.settings = settings
        self.manager = manager or RuntimeDependencyManager(settings)
        self.dispatch = dispatch
        self.prepare_voice = prepare_voice
        self.logger = logger
        self._start_worker = start_worker or (lambda fn: Thread(target=fn, daemon=True, name="aurora-runtime-probe").start())
        self._observers = []
        self._generation = 0
        self._running = False
        self._closed = False
        self._reevaluate = False
        self._process_token = uuid4().hex
        self.snapshot = RuntimeSnapshot(0, json.dumps(empty_runtime_report()))

    def subscribe(self, callback):
        self._observers.append(callback)
        callback(self.snapshot)
        return lambda: self._observers.remove(callback) if callback in self._observers else None

    def _notify(self):
        for callback in tuple(self._observers):
            try:
                callback(self.snapshot)
            except Exception:
                if self.logger:
                    self.logger.exception("Runtime snapshot observer failed")

    def refresh(self, *, reevaluate=False):
        if self._closed:
            return
        self._generation += 1
        self._reevaluate = self._reevaluate or reevaluate
        self.snapshot = RuntimeSnapshot(self.snapshot.revision, self.snapshot.payload, checking=True)
        self._notify()
        if not self._running:
            self._launch()

    def _launch(self):
        self._running = True
        generation = self._generation
        reevaluate, self._reevaluate = self._reevaluate, False
        buffered = _ProbeSettings(self.settings) if hasattr(self.settings, "data") else None

        def probe():
            original = self.manager.settings
            try:
                if buffered is not None:
                    self.manager.settings = buffered
                report = self.manager.check(timeout=5.0, reevaluate_models=reevaluate)
                failed = False
            except Exception:
                report, failed = empty_runtime_report(), True
                if self.logger:
                    self.logger.exception("Runtime probe failed")
            finally:
                self.manager.settings = original
            if not self._closed:
                try:
                    self.dispatch(lambda: self._finish(generation, report, failed, buffered, reevaluate))
                except Exception:
                    if not self._closed and self.logger:
                        self.logger.exception("Runtime notification dispatch failed")

        self._start_worker(probe)

    def _finish(self, generation, report, failed, buffered, reevaluate):
        self._running = False
        if self._closed:
            return
        if generation != self._generation:
            self._reevaluate = self._reevaluate or reevaluate
            self._launch()
            return
        if failed:
            enabled = bool(self.settings.get("voice.enabled", False))
            report["voice"] = {"enabled": enabled, "ready": False,
                               "status": "Degraded" if enabled else "Optional"}
            report.setdefault("domains", {})["voice"] = {
                "status": report["voice"]["status"], "available": False,
                "data": {"enabled": enabled},
            }
        try:
            if buffered is not None and buffered.updates and not failed:
                self.settings.update_many(buffered.updates, save=True)
            self._clear_loaded_restart(report)
            if self.prepare_voice is not None:
                self.prepare_voice(report)
            if report.get("voice", {}).get("ready"):
                if not self.settings.get("runtime.voice_configured", False):
                    self.settings.set("runtime.voice_configured", True)
        except Exception:
            failed = True
            mark_voice_unavailable(report, "initialization_failed")
            if self.logger:
                self.logger.exception("Runtime hot apply failed")
        self.snapshot = RuntimeSnapshot(
            self.snapshot.revision + 1, json.dumps(report), error=failed,
            restart_required=bool(self.settings.get("runtime.restart_required", False)),
            restart_reason=str(self.settings.get("runtime.restart_reason", "")),
        )
        if self.logger:
            voice = report.get("voice", {})
            self.logger.info(f"Runtime snapshot revision={self.snapshot.revision} voice={voice.get('status')} ready={voice.get('ready')} restart_required={self.snapshot.restart_required}")
        self._notify()

    def require_native_restart(self, reason):
        """For a verified native-loader limitation, never for ordinary checks."""
        if not reason:
            raise ValueError("a verified native-loader reason is required")
        self.settings.update_many({"runtime.restart_required": True,
                                   "runtime.restart_reason": str(reason),
                                   "runtime.restart_process": self._process_token}, save=True)
        self.refresh()

    def _clear_loaded_restart(self, report):
        if not self.settings.get("runtime.restart_required", False):
            return
        if self.settings.get("runtime.restart_process", "") == self._process_token:
            return
        items = report.get("items_by_key", {})
        native_ready = (items.get("stt", {}).get("available") is True
                        and items.get("tts", {}).get("available") is True
                        and items.get("playback", {}).get("data", {}).get("runtime_available") is True)
        if native_ready:
            self.settings.update_many({"runtime.restart_required": False,
                                       "runtime.restart_reason": "", "runtime.restart_process": ""}, save=True)

    def close(self):
        self._closed = True
        self._observers.clear()


def mark_voice_unavailable(report, reason):
    voice = report.setdefault("voice", {})
    voice.update(ready=False, status="Degraded", initialization_error=reason)
    report["status"] = "Degraded"
    domain = report.setdefault("domains", {}).setdefault("voice", {})
    domain.update(status="Degraded", available=False)
    summary = voice.get("summary", {})
    summary.update(status="Degraded", available=False, detail=reason)
    for item in report.get("items", []):
        if item.get("key") == "voice":
            item.update(status="Degraded", available=False, detail=reason)
    if "voice" in report.get("items_by_key", {}):
        report["items_by_key"]["voice"].update(status="Degraded", available=False, detail=reason)


def shared_runtime_state(settings, parent, manager=None):
    """Compatibility composition for standalone widgets, still one per store."""
    state = getattr(settings, "_runtime_state", None)
    if state is None:
        root = parent.winfo_toplevel()
        state = RuntimeState(settings, dispatch=lambda fn: root.after(0, fn), manager=manager)
        settings._runtime_state = state
        state.refresh()
    return state
