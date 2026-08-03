from pathlib import Path
from threading import Event

from modules.experience.audio import (
    PlaybackEventType,
    RealPlaybackController,
)
from modules.experience.voice.models import SpeechResult


class FakeMusic:
    def __init__(self, busy_sequence=None, load_error=None, play_error=None, stop_error=None):
        self.busy_sequence = list(busy_sequence or [True, False])
        self.load_error = load_error
        self.play_error = play_error
        self.stop_error = stop_error
        self.loaded = []
        self.play_calls = 0
        self.stop_calls = 0

    def load(self, path):
        if self.load_error:
            raise self.load_error
        self.loaded.append(path)

    def play(self):
        if self.play_error:
            raise self.play_error
        self.play_calls += 1

    def stop(self):
        if self.stop_error:
            raise self.stop_error
        self.stop_calls += 1

    def get_busy(self):
        return self.busy_sequence.pop(0) if self.busy_sequence else False


class FakeMixer:
    def __init__(self, music):
        self.music = music


def test_mp3_file_playback_emits_started_and_completed(tmp_path):
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake mp3")
    music = FakeMusic()
    controller = RealPlaybackController(mixer=FakeMixer(music), poll_interval=0.01)
    events = []
    completed = Event()

    def on_event(event):
        events.append(event)
        if event.event_type is PlaybackEventType.COMPLETED:
            completed.set()

    controller.subscribe(on_event)
    controller.play(SpeechResult(audio_path=str(audio_path), mime_type="audio/mpeg"))

    assert completed.wait(1) is True
    assert music.loaded == [str(audio_path)]
    assert [event.event_type for event in events] == [
        PlaybackEventType.STARTED,
        PlaybackEventType.COMPLETED,
    ]
    assert controller.is_playing() is False


def test_missing_file_emits_failed_event():
    controller = RealPlaybackController(mixer=FakeMixer(FakeMusic()))
    events = []
    controller.subscribe(events.append)

    controller.play(SpeechResult(audio_path="missing.mp3"))

    assert events[0].event_type is PlaybackEventType.FAILED
    assert "does not exist" in events[0].error


def test_audio_load_failure_emits_failed_event(tmp_path):
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"invalid mp3")
    controller = RealPlaybackController(
        mixer=FakeMixer(FakeMusic(load_error=RuntimeError("load failed")))
    )
    events = []
    controller.subscribe(events.append)

    controller.play(SpeechResult(audio_path=str(audio_path)))

    assert events[0].event_type is PlaybackEventType.FAILED
    assert events[0].error == "load failed"
    assert controller.is_playing() is False


def test_stop_emits_stopped_event(tmp_path):
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake mp3")
    music = FakeMusic(busy_sequence=[True, True])
    controller = RealPlaybackController(mixer=FakeMixer(music), poll_interval=0.1)
    events = []
    controller.subscribe(events.append)

    controller.play(SpeechResult(audio_path=str(audio_path)))
    controller.stop()

    assert [event.event_type for event in events] == [
        PlaybackEventType.STARTED,
        PlaybackEventType.STOPPED,
    ]
    assert music.stop_calls == 1
    assert controller.is_playing() is False


def test_unavailable_pygame_emits_failed_event_without_raising(tmp_path):
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake mp3")
    controller = RealPlaybackController()
    events = []
    controller.subscribe(events.append)

    controller.play(SpeechResult(audio_path=str(audio_path)))

    assert events[0].event_type is PlaybackEventType.FAILED
