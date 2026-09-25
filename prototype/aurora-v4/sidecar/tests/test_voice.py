"""Deterministic completed-turn Voice integration; no cloud, model or device."""
import asyncio
import copy
import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from test_production_sidecar import ProductionComposition, ROOT, envelope, write_settings
from test_direct_chat import model_server, request, cancel
from production_sidecar.server import ProductionSidecar
from production_sidecar.voice import VoiceExecution
from modules.settings_service import SettingsService, SettingsError
from modules.experience.voice.fake import FakeTextToSpeechProvider
from modules.experience.voice.models import SpeechResult
from modules.experience.voice.tts_router import TTSRouter
from modules.experience.audio.fake_audio import FakePlayback
from modules.experience.audio.playback import PlaybackEvent, PlaybackEventType
from validate_contracts import validate_message, ContractError


class Playback(FakePlayback):
    def shutdown(self):
        self.stop()


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Voice deadline exceeded")
        time.sleep(.005)


@pytest.fixture
def voice(tmp_path):
    config = write_settings(tmp_path, "http://127.0.0.1:1", voice={"enabled": True})
    settings = SettingsService(config)
    provider = FakeTextToSpeechProvider()
    playback = Playback()
    events = []
    instance = VoiceExecution(settings, events.append,
        router_factory=lambda *_: TTSRouter({"fake": provider}, default_provider="fake"),
        playback_factory=lambda: playback)
    instance.begin("g1", "connection")
    yield instance, settings, provider, playback, events
    instance.close()
    settings.close()
    assert not instance._workers


def test_disabled_never_calls_provider(voice):
    v, settings, provider, _, _ = voice
    settings.apply_patch({"voice.enabled": False}, settings.revision)
    assert not v.completed("g1", "完整回复")
    assert not provider.requests


def test_enabled_final_only_once_and_completion(voice):
    v, _, provider, playback, events = voice
    assert v.completed("g1", "完整回复")
    assert not v.completed("g1", "重复 terminal")
    wait_for(playback.is_playing)
    assert v.snapshot()["state"] == "speaking"
    playback.complete()
    wait_for(lambda: v.snapshot()["state"] == "idle")
    assert [x[0] for x in provider.requests] == ["完整回复"]
    assert [e["state"] for e in events] == ["idle", "preparing", "speaking", "idle"]


def test_stop_before_terminal_suppresses_orphan(voice):
    v, _, provider, _, _ = voice
    v.stop("g1")
    assert not v.completed("g1", "should not play")
    assert not provider.requests


def test_stop_is_real_idempotent_and_cleanup(voice):
    v, _, _, playback, _ = voice
    v.completed("g1", "完整回复")
    wait_for(playback.is_playing)
    v.stop("g1")
    v.stop("g1")
    wait_for(lambda: v.snapshot()["state"] == "idle")
    assert not playback.is_playing()
    assert playback.stop_calls > 0
    v.close()
    v.close()
    assert not [t for t in threading.enumerate() if t.name == "aurora-v4-voice"]


def test_stale_callback_and_old_stop_cannot_touch_next_turn(voice):
    v, _, _, playback, _ = voice
    v.completed("g1", "old")
    wait_for(playback.is_playing)
    old = playback.played[-1]
    callbacks = list(playback._subscribers)
    v.begin("g2", "connection")
    v.completed("g2", "new")
    wait_for(lambda: len(playback.played) == 2)
    for callback in callbacks:
        callback(PlaybackEvent(PlaybackEventType.FAILED, speech=old, error="late"))
    v.stop("g1")
    assert v.snapshot()["generation_id"] == "g2"
    assert v.snapshot()["state"] == "speaking"
    assert playback.is_playing()
    assert not v.completed("g1", "late terminal")


def test_cancel_provider_failure_side_effect_stays_idle(voice):
    v, _, _, playback, _ = voice
    entered = threading.Event()
    class Blocked(FakeTextToSpeechProvider):
        def synthesize(self, text, options=None, *, cancel_event, **kwargs):
            entered.set()
            assert cancel_event.wait(3)
            raise OSError("incomplete response private endpoint")
    v.router_factory = lambda *_: TTSRouter({"fake": Blocked()}, default_provider="fake")
    v.completed("g1", "old")
    assert entered.wait(2)
    v.stop("g1")
    wait_for(lambda: v.snapshot()["state"] == "idle")
    assert v.snapshot()["error_code"] == ""
    assert not playback.played


@pytest.mark.parametrize("failure,expected", [("provider", "SYNTHESIS_FAILED"), ("playback", "PLAYBACK_FAILED")])
def test_safe_error_events(voice, failure, expected):
    v, _, provider, playback, events = voice
    if failure == "provider":
        provider.error = RuntimeError("SECRET-private-url")
    else:
        playback.play_error = RuntimeError("SECRET-device")
    v.completed("g1", "SECRET-content")
    wait_for(lambda: v.snapshot()["state"] == "error")
    assert v.snapshot()["error_code"] == expected
    assert "SECRET" not in json.dumps(events)


def test_disable_during_preparing_and_shutdown_joins(voice):
    v, settings, _, playback, _ = voice
    entered = threading.Event()
    class Blocked(FakeTextToSpeechProvider):
        def synthesize(self, text, options=None, *, cancel_event, **kwargs):
            entered.set()
            assert cancel_event.wait(3)
            return SpeechResult(audio_bytes=b"cancelled")
    v.router_factory = lambda *_: TTSRouter({"fake": Blocked()}, default_provider="fake")
    v.completed("g1", "text")
    assert entered.wait(2)
    settings.apply_patch({"voice.enabled": False}, settings.revision)
    v.settings_changed()
    v.close()
    assert not playback.played
    assert not v._workers


def test_settings_survive_restart_conflict_and_endpoint_remains_private(tmp_path):
    config = write_settings(tmp_path, "http://127.0.0.1:1", voice={"tts": {"remote_cosyvoice": {"url": "http://private-node:8000"}}})
    settings = SettingsService(config)
    settings.apply_patch({"voice.enabled": True, "voice.tts.provider": "remote_cosyvoice"}, 0)
    with pytest.raises(SettingsError, match="Settings"):
        settings.apply_patch({"voice.enabled": False}, 0)
    restored = SettingsService(config)
    assert restored.get("voice.enabled") is True
    assert restored.get("voice.tts.provider") == "remote_cosyvoice"
    assert restored.get("voice.tts.remote_cosyvoice.url") == "http://private-node:8000"
    assert "private-node" not in json.dumps(restored.describe())
    with pytest.raises(SettingsError):
        restored.apply_patch({"voice.tts.remote_cosyvoice.url": "http://new"}, 0)


def test_voice_wire_schema_rejects_secrets_and_wrong_shapes():
    import jsonschema
    schema = json.loads((ROOT / "prototype/aurora-v4/contracts/ipc-v1.schema.json").read_text())
    snapshot = dict(revision=1, state="speaking", enabled=True, provider="edge_tts", generation_id="g1", error_code="")
    event = dict(protocol="aurora-ipc", version=1, type="voice.changed", payload=snapshot)
    validate_message(event)
    jsonschema.validate(event, schema)
    for field in ("text", "endpoint", "path", "token", "worker_id"):
        bad = copy.deepcopy(event)
        bad["payload"][field] = "private"
        with pytest.raises(ContractError):
            validate_message(bad)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)
    for kind, payload in [("voice.get.request", {}), ("voice.stop.request", {"target_generation_id": "g1"}),
                          ("voice.get.response", snapshot), ("voice.stop.response", snapshot)]:
        message = envelope(kind, **payload)
        validate_message(message)
        jsonschema.validate(message, schema)


@pytest.mark.parametrize("mode", ["enabled", "disabled", "failure", "unavailable", "cancelled"])
def test_real_chat_terminal_and_persistence_isolated(tmp_path, mode):
    async def check(host):
        settings_file = write_settings(tmp_path, host, voice={"enabled": mode != "disabled"},
                                      persona={"enabled": False}, knowledge={"enabled": False}, rag={"pipeline_enabled": False})
        c = ProductionComposition(ROOT, settings_file, conversation_root=tmp_path / "conversations", context_root=tmp_path)
        sidecar = ProductionSidecar("token", c)
        provider = FakeTextToSpeechProvider(error=RuntimeError("private") if mode == "failure" else None)
        playback = Playback()
        if mode == "unavailable":
            from modules.experience.voice.providers.remote_cosyvoice import RemoteCosyVoiceProvider
            provider = RemoteCosyVoiceProvider("http://127.0.0.1:1")
        c.voice.router_factory = lambda *_: TTSRouter({"fake": provider}, default_provider="fake")
        c.voice.playback_factory = lambda: playback
        events = []
        async def send(connection, event):
            validate_message(event)
            events.append(event)
        sidecar.send = send
        conversation = c.conversations.create()
        message = request()
        message["payload"]["conversation_id"] = conversation["conversation_id"]
        try:
            await sidecar.start_chat("connection", message)
            run = sidecar.chat.active
            if mode == "cancelled":
                await sidecar.cancel_chat("connection", cancel())
            await asyncio.wait_for(run.task, 5)
            terminal = [e for e in events if e["type"] == "chat.completed"]
            assert len(terminal) == 1
            expected = "cancelled" if mode == "cancelled" else "completed"
            assert terminal[0]["payload"]["terminal_state"] == expected
            if mode in {"enabled", "failure", "unavailable"}:
                await asyncio.to_thread(wait_for, lambda: c.voice.snapshot()["state"] in {"speaking", "error"})
                if mode != "enabled":
                    assert c.voice.snapshot()["state"] == "error"
            else:
                assert not provider.requests
            c.voice.stop("g1")
            assert len(c.conversations.history(conversation["conversation_id"])) == (0 if mode == "cancelled" else 2)
        finally:
            await sidecar.cancel_all()
            c.close()
    with model_server("blocked" if mode == "cancelled" else "success") as (host, _):
        asyncio.run(check(host))
