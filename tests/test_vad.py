from array import array
from threading import Event

from modules.experience.audio.vad import (
    AudioFrameSource,
    FakeVAD,
    RMSVADAdapter,
    VADAdapterError,
    VoiceActivityType,
)


class FakeFrames(AudioFrameSource):
    def __init__(self, frames):
        self.frames = list(frames)

    def read_frame(self, cancel_event, timeout_seconds):
        return self.frames.pop(0) if self.frames else None


def pcm(value, count=320):
    return array("h", [value] * count).tobytes()


def test_rms_vad_detects_voice_after_minimum_duration():
    vad = RMSVADAdapter(FakeFrames([pcm(0), pcm(2000), pcm(2000)]), minimum_active_duration_ms=40)
    event = vad.wait_for_voice(Event(), 1)
    assert event.event_type is VoiceActivityType.STARTED
    assert event.active is True


def test_fake_vad_timeout_and_cancel():
    assert FakeVAD(timeout=True).wait_for_voice(Event(), 0.01) is None
    cancel = Event()
    event = FakeVAD(cancel=True).wait_for_voice(cancel, 0.01)
    assert event.event_type is VoiceActivityType.STOPPED
    assert cancel.is_set()


def test_vad_source_error_is_controlled():
    class Broken(AudioFrameSource):
        def read_frame(self, cancel_event, timeout_seconds):
            raise OSError("microphone unavailable")

    try:
        RMSVADAdapter(Broken()).wait_for_voice(Event(), 1)
    except VADAdapterError as error:
        assert error.code == "frame_source_error"
    else:
        raise AssertionError("expected VAD source error")


def test_rms_vad_requires_five_consecutive_candidate_frames_and_reports_diagnostics():
    frames = [pcm(0), pcm(500), pcm(500), pcm(500), pcm(0)]
    vad = RMSVADAdapter(
        FakeFrames(frames),
        threshold=0.014,
        peak_threshold=None,
        minimum_active_duration_ms=100,
    )

    event = vad.wait_for_voice(Event(), 0.1)

    assert event is None
    metrics = vad.last_wait_diagnostics["metrics"]
    assert metrics["frames_checked"] == 5
    assert metrics["above_threshold_frames"] == 3
    assert metrics["max_rms"] > 0.014
    assert metrics["trigger_failure_reason"] == "insufficient_consecutive_frames"


def test_rms_vad_accepts_three_consecutive_peak_candidates():
    frames = [pcm(0), pcm(500), pcm(500), pcm(500)]
    vad = RMSVADAdapter(
        FakeFrames(frames),
        threshold=0.02,
        peak_threshold=0.01,
        minimum_active_duration_ms=60,
    )

    event = vad.wait_for_voice(Event(), 0.1)

    assert event.event_type is VoiceActivityType.STARTED
    assert event.diagnostics["metrics"]["above_threshold_frames"] == 3
    assert event.diagnostics["metrics"]["max_peak"] > 0.01
