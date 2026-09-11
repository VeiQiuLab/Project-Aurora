import json

from modules.experience.audio import StreamingPlaybackReport
from modules.experience.voice.models import StreamingSpeechResult
from scripts import smoke_voice_node_stream_playback as smoke


def test_keyboard_interrupt_cancels_session_and_prints_terminal_state(
    monkeypatch, capsys
):
    speech = StreamingSpeechResult(
        metadata={
            "sample_format": "s16le",
            "bits_per_sample": 16,
            "sample_rate": 24000,
            "channels": 1,
        },
        chunks=iter(()),
        diagnostics={"success": True, "reason": "stream_open"},
    )

    class FakeProvider:
        def __init__(self, *_args, **_kwargs):
            pass

        def synthesize_stream(self, *_args, **_kwargs):
            return speech

    class FakeSession:
        def __init__(self):
            self.cancel_invocations = 0
            self.close_invocations = 0
            self.cancelled = False
            self.provider_closed = False
            self.audio_stream_stopped = False

        def wait(self, _timeout=None):
            if not self.cancelled:
                raise KeyboardInterrupt
            return StreamingPlaybackReport(
                status="cancelled",
                diagnostics={
                    "metrics": {
                        "cancel_requested_monotonic": 10.0,
                        "cancel_completed_monotonic": 10.001,
                        "cancel_latency_ms": 1.0,
                        "provider_closed": True,
                        "audio_stream_stopped": True,
                    }
                },
            )

        def cancel(self):
            self.cancel_invocations += 1
            self.cancelled = True
            self.provider_closed = True
            self.audio_stream_stopped = True

        def close(self):
            self.close_invocations += 1
            self.cancelled = True

        def threads_alive(self):
            return ()

        def diagnostics_snapshot(self):
            return {"metrics": {}}

    session = FakeSession()

    class FakeController:
        def __init__(self, **_kwargs):
            pass

        def play(self, *_args, **_kwargs):
            return session

    monkeypatch.setattr(smoke, "RemoteCosyVoiceProvider", FakeProvider)
    monkeypatch.setattr(smoke, "StreamingPlaybackController", FakeController)
    monkeypatch.setattr(smoke, "_health", lambda _url: {"status": "ready"})

    exit_code = smoke.main(
        [
            "--url",
            "http://voice-node.test:8765",
            "--text",
            "需要取消的语音",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 130
    assert payload["status"] == "cancelled"
    assert payload["cancel_requested_monotonic"] == 10.0
    assert payload["cancel_completed_monotonic"] == 10.001
    assert payload["cancel_latency_ms"] >= 0
    assert payload["handler_latency_ms"] >= 0
    assert payload["producer_thread_alive"] is False
    assert payload["playback_thread_alive"] is False
    assert payload["provider_closed"] is True
    assert payload["audio_stream_stopped"] is True
    assert session.cancel_invocations == 1
    assert session.close_invocations == 2
