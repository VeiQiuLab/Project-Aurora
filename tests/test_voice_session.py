import time

from modules.experience.state import CompanionState, CompanionStateStore
from modules.experience.audio import FakeFFmpegAudioFrameSource, FrameRecorder
from modules.experience.audio.frame_pipeline import AudioFrameBuffer
from modules.experience.audio.vad import FakeVAD, VADAdapter
from modules.experience.voice.models import TranscriptionResult
from modules.experience.voice.orchestrator import VoiceOrchestrationResult
from modules.experience.voice.session import VoiceSessionManager


def test_session_enters_ready_runs_cycle_and_returns_to_idle():
    store = CompanionStateStore()
    wait_calls = {"count": 0}
    cleanup_calls = []

    def wait_for_voice(_cancel, _timeout):
        wait_calls["count"] += 1
        return wait_calls["count"] == 1

    manager = VoiceSessionManager(
        state_store=store,
        wait_for_voice=wait_for_voice,
        run_cycle=lambda: VoiceOrchestrationResult(
            success=True,
            transcription=TranscriptionResult(text="hello"),
        ),
        cleanup_microphone=lambda: cleanup_calls.append(True),
        inactivity_timeout_seconds=0.02,
        wait_slice_seconds=0.005,
    )
    assert manager.start_session() is True
    while manager.session_running:
        time.sleep(0.005)

    assert manager.last_result.reason == "inactivity_timeout"
    assert manager.last_result.diagnostics["metrics"]["valid_inputs"] == 1
    assert store.current_state is CompanionState.IDLE
    assert cleanup_calls


def test_cancel_session_cleans_up_and_returns_to_idle():
    store = CompanionStateStore()
    manager = VoiceSessionManager(
        state_store=store,
        wait_for_voice=lambda cancel, _timeout: (cancel.wait(0.01) and False),
        run_cycle=lambda: VoiceOrchestrationResult(success=True),
        inactivity_timeout_seconds=10,
    )
    assert manager.start_session() is True
    assert manager.cancel_session() is True
    while manager.session_running:
        time.sleep(0.005)

    assert manager.last_result.cancelled is True
    assert store.current_state is CompanionState.IDLE


def test_frame_pipeline_session_passes_recorded_audio_to_orchestrator(tmp_path):
    store = CompanionStateStore()
    buffer = AudioFrameBuffer(max_duration_ms=1000)
    vad_reader = buffer.subscribe()
    source = FakeFFmpegAudioFrameSource(buffer, [b"\x00\x01" * 320, b"\x02\x03" * 320])
    captured = []

    class Cycle:
        def __init__(self, recorder):
            self.recorder = recorder

        def run(self):
            self.recorder.start()
            audio = self.recorder.stop()
            captured.append(audio)
            return VoiceOrchestrationResult(
                success=True,
                transcription=TranscriptionResult(text="frame input"),
            )

    fake_vad = FakeVAD()

    class OneShotVAD(VADAdapter):
        def __init__(self):
            self.first = True

        def wait_for_voice(self, cancel_event, timeout_seconds):
            if self.first:
                self.first = False
                return fake_vad.wait_for_voice(cancel_event, timeout_seconds)
            return None

    manager = VoiceSessionManager(
        state_store=store,
        vad_adapter=OneShotVAD(),
        audio_buffer=buffer,
        audio_source=source,
        orchestrator_factory=Cycle,
        frame_recorder_factory=lambda reader: FrameRecorder(
            reader, output_dir=tmp_path, min_duration_ms=20
        ),
        pre_roll_ms=1000,
        recording_window_seconds=0.05,
        inactivity_timeout_seconds=0.2,
    )
    assert manager.start_session() is True
    while manager.session_running:
        time.sleep(0.005)

    assert captured and captured[0].kind == "file"
    assert manager.last_result.reason == "inactivity_timeout"
    assert manager.last_result.diagnostics["metrics"]["pipeline_cycles"]
    assert store.current_state is CompanionState.IDLE
