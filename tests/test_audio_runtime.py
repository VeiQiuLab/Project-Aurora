import pytest

from modules.experience.audio import (
    AudioPlaybackController,
    AudioRecorder,
    FakePlayback,
    FakeRecorder,
)
from modules.experience.voice.models import AudioInput, SpeechResult


def test_fake_recorder_implements_contract_and_returns_fixed_audio():
    audio = AudioInput(kind="bytes", data=b"recorded")
    recorder = FakeRecorder(audio)

    assert isinstance(recorder, AudioRecorder)
    recorder.start()
    assert recorder.stop() == audio
    assert recorder.start_calls == 1
    assert recorder.stop_calls == 1


def test_fake_playback_implements_contract_and_tracks_playback():
    speech = SpeechResult(audio_bytes=b"speech")
    playback = FakePlayback()

    assert isinstance(playback, AudioPlaybackController)
    playback.play(speech)
    assert playback.is_playing() is True
    assert playback.played == [speech]
    playback.stop()
    assert playback.is_playing() is False
    assert playback.stop_calls == 1


def test_fake_recorder_cancel_stops_recording_without_audio_output():
    recorder = FakeRecorder()

    recorder.start()
    recorder.cancel()

    assert recorder.cancel_calls == 1
    assert recorder.stop_calls == 0
    with pytest.raises(RuntimeError, match="not active"):
        recorder.stop()


def test_fake_recorder_failure_is_injectable():
    recorder = FakeRecorder(start_error=RuntimeError("microphone unavailable"))

    with pytest.raises(RuntimeError, match="microphone unavailable"):
        recorder.start()


def test_fake_playback_failure_is_injectable():
    playback = FakePlayback(play_error=RuntimeError("speaker unavailable"))

    with pytest.raises(RuntimeError, match="speaker unavailable"):
        playback.play(SpeechResult(audio_bytes=b"speech"))
