import json

from modules.experience.voice.orchestrator import VoiceOrchestrationResult
from scripts import smoke_voice_orchestrator_stream_playback as smoke


class FakeRuntime:
    def __init__(self, results, *, interrupt=False):
        self.results = list(results)
        self.interrupt = interrupt
        self.started = 0
        self.cancel_calls = 0
        self.close_calls = 0

    def start_voice_session(self):
        self.started += 1
        return True

    @property
    def session_running(self):
        if self.interrupt:
            self.interrupt = False
            raise KeyboardInterrupt
        return False

    def cancel_voice_session(self):
        self.cancel_calls += 1
        return True

    def wait_for_session(self, _timeout):
        return self.results.pop(0)

    def close(self):
        self.close_calls += 1
        return True


def test_orchestrator_smoke_uses_runtime_composition_and_can_repeat(
    monkeypatch, capsys
):
    captured = {}
    runtime = FakeRuntime(
        [
            VoiceOrchestrationResult(success=True, stage="completed"),
            VoiceOrchestrationResult(success=True, stage="completed"),
        ]
    )

    def create_runtime(settings, **kwargs):
        captured["settings"] = settings
        captured["kwargs"] = kwargs
        return runtime

    monkeypatch.setattr(smoke, "create_voice_runtime", create_runtime)

    exit_code = smoke.main(
        [
            "--url",
            "http://voice-node.test:8765",
            "--text",
            "真实编排流式播放",
            "--repeat",
            "2",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert runtime.started == 2
    assert runtime.close_calls == 1
    assert payload["status"] == "completed"
    assert payload["runtime_closed"] is True
    assert len(payload["requests"]) == 2
    settings = captured["settings"]
    assert settings["voice"]["tts"]["provider"] == "remote_cosyvoice"
    assert settings["voice"]["tts"]["streaming_enabled"] is True
    assert settings["voice"]["tts"]["remote_cosyvoice"]["url"] == (
        "http://voice-node.test:8765"
    )
    assert callable(captured["kwargs"]["text_input_handler"])


def test_orchestrator_smoke_keyboard_interrupt_uses_runtime_cancel(
    monkeypatch, capsys
):
    runtime = FakeRuntime(
        [VoiceOrchestrationResult(success=False, cancelled=True, stage="cancelled")],
        interrupt=True,
    )
    monkeypatch.setattr(smoke, "create_voice_runtime", lambda *_args, **_kwargs: runtime)

    exit_code = smoke.main(
        [
            "--url",
            "http://voice-node.test:8765",
            "--text",
            "取消测试",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 130
    assert runtime.cancel_calls == 1
    assert runtime.close_calls == 1
    assert payload["status"] == "cancelled"
    assert payload["runtime_closed"] is True
