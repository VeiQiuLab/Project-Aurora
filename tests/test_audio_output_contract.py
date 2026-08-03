import pytest

from modules.experience.audio import (
    FakePlayback,
    PlaybackEventType,
)
from modules.experience.state import CompanionState, CompanionStateStore
from modules.experience.voice.fake import FakeTextToSpeechProvider
from modules.experience.voice.models import SpeechResult, VoiceOptions


def connect_playback_to_state(playback, state_store):
    def handle(event):
        if event.event_type is PlaybackEventType.STARTED:
            state_store.transition(CompanionState.SPEAKING, source="playback_test")
        elif event.event_type in (
            PlaybackEventType.COMPLETED,
            PlaybackEventType.STOPPED,
        ):
            state_store.force_idle(source="playback_test")
        elif event.event_type is PlaybackEventType.FAILED:
            state_store.transition(CompanionState.ERROR, source="playback_test")
            state_store.force_idle(source="playback_test")

    playback.subscribe(handle)
    return handle


def test_fake_tts_result_flows_to_playback_events_and_state():
    tts = FakeTextToSpeechProvider()
    playback = FakePlayback()
    state_store = CompanionStateStore()
    state_store.transition(CompanionState.THINKING)
    events = []
    playback.subscribe(lambda event: events.append(event.event_type))
    connect_playback_to_state(playback, state_store)

    speech = tts.synthesize("hello", VoiceOptions(voice="aurora"))
    playback.play(speech)
    assert state_store.current_state is CompanionState.SPEAKING
    playback.complete()

    assert events == [PlaybackEventType.STARTED, PlaybackEventType.COMPLETED]
    assert state_store.current_state is CompanionState.IDLE


def test_playback_failure_emits_event_and_recovers_state():
    playback = FakePlayback(play_error=RuntimeError("speaker unavailable"))
    state_store = CompanionStateStore()
    state_store.transition(CompanionState.THINKING)
    received = []
    playback.subscribe(received.append)
    connect_playback_to_state(playback, state_store)

    with pytest.raises(RuntimeError, match="speaker unavailable"):
        playback.play(SpeechResult(audio_bytes=b"speech"))

    assert received[0].event_type is PlaybackEventType.FAILED
    assert state_store.current_state is CompanionState.IDLE


def test_user_stop_emits_stopped_and_recovers_state():
    playback = FakePlayback()
    state_store = CompanionStateStore()
    state_store.transition(CompanionState.THINKING)
    connect_playback_to_state(playback, state_store)

    playback.play(SpeechResult(audio_bytes=b"speech"))
    playback.stop()

    assert playback.is_playing() is False
    assert state_store.current_state is CompanionState.IDLE


def test_empty_text_is_rejected_before_audio_generation():
    with pytest.raises(ValueError, match="must not be empty"):
        FakeTextToSpeechProvider().synthesize("   ")


def test_tts_exception_does_not_change_state_by_itself():
    state_store = CompanionStateStore()
    tts = FakeTextToSpeechProvider(error=RuntimeError("tts unavailable"))

    with pytest.raises(RuntimeError, match="tts unavailable"):
        tts.synthesize("hello")

    assert state_store.current_state is CompanionState.IDLE
