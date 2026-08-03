from pathlib import Path

import pytest

from modules.experience.audio.recorder import (
    AudioRecorder,
    AudioRecorderError,
    MicrophoneRecorder,
)
from modules.experience.voice.models import AudioInput


class FakeMicrophone:
    def __init__(self, payload=b"\x00\x01\x02\x03"):
        self.payload = payload
        self.stop_calls = 0

    class Stream:
        def __init__(self, owner, callback):
            self.owner = owner
            self.callback = callback

        def start(self):
            self.callback(
                type("Chunk", (), {"copy": lambda _self: type("Data", (), {"tobytes": lambda _self: self.owner.payload})()})(),
                2,
                None,
                None,
            )

        def stop(self):
            self.owner.stop_calls += 1

        def close(self):
            return None

    def InputStream(self, *, callback, **_kwargs):
        return self.Stream(self, callback)


def test_microphone_recorder_contract_and_output(tmp_path):
    backend = FakeMicrophone()
    recorder = MicrophoneRecorder(audio_backend=backend, output_dir=tmp_path)

    assert isinstance(recorder, AudioRecorder)
    recorder.start()
    audio = recorder.stop()

    assert isinstance(audio, AudioInput)
    assert audio.kind == "microphone"
    assert audio.path and Path(audio.path).exists()
    assert backend.stop_calls == 1


def test_microphone_recorder_cancel_is_push_to_talk_safe():
    backend = FakeMicrophone()
    recorder = MicrophoneRecorder(audio_backend=backend)

    recorder.start()
    recorder.cancel()
    recorder.cancel()

    assert backend.stop_calls == 1


def test_microphone_recorder_reports_missing_device():
    class BrokenMicrophone:
        class Stream:
            def start(self):
                raise OSError("no input device")

        def InputStream(self, **_kwargs):
            return self.Stream()
            raise OSError("no input device")

    recorder = MicrophoneRecorder(audio_backend=BrokenMicrophone())
    with pytest.raises(AudioRecorderError) as error:
        recorder.start()

    assert error.value.code == "microphone_unavailable"
    assert error.value.diagnostics["success"] is False


def test_microphone_recorder_requires_active_session_to_stop():
    recorder = MicrophoneRecorder(audio_backend=FakeMicrophone())
    with pytest.raises(AudioRecorderError) as error:
        recorder.stop()
    assert error.value.code == "not_recording"
