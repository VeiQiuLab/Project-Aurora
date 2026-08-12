import time
import wave
from array import array

from modules.experience.audio.frame_pipeline import AudioFrameBuffer
from modules.experience.audio.frame_recorder import FrameRecorder


def pcm(value=1000, samples=320):
    return array("h", [value] * samples).tobytes()


def test_frame_recorder_writes_ordered_preroll_wav(tmp_path):
    buffer = AudioFrameBuffer(max_duration_ms=1000)
    buffer.publish(pcm(), diagnostics={"pre_roll": True})
    reader = buffer.subscribe(pre_roll_ms=1000)
    recorder = FrameRecorder(reader, output_dir=tmp_path, min_duration_ms=20)
    recorder.start()
    buffer.publish(pcm(2000))
    time.sleep(0.03)
    audio = recorder.stop()

    assert audio.kind == "file"
    assert audio.diagnostics["frame_count"] >= 2
    assert audio.diagnostics["first_sequence"] == 1
    assert audio.diagnostics["pre_roll_frames"] == 1
    with wave.open(audio.path, "rb") as wav_file:
        assert wav_file.getnframes() > 0


def test_frame_recorder_cancel_discards_frames(tmp_path):
    buffer = AudioFrameBuffer()
    reader = buffer.subscribe()
    recorder = FrameRecorder(reader, output_dir=tmp_path)
    recorder.start()
    buffer.publish(pcm())
    recorder.cancel()

    assert list(tmp_path.iterdir()) == []


def test_frame_recorder_manual_stop_preserves_stop_reason(tmp_path):
    buffer = AudioFrameBuffer()
    reader = buffer.subscribe()
    recorder = FrameRecorder(reader, output_dir=tmp_path, min_duration_ms=20)
    recorder.start()
    buffer.publish(pcm(2000))
    time.sleep(0.03)
    audio = recorder.stop()

    assert audio.diagnostics["stop_reason"] == "manual_stop"


def test_frame_recorder_default_silence_threshold_is_800ms(tmp_path):
    buffer = AudioFrameBuffer()
    reader = buffer.subscribe()
    recorder = FrameRecorder(reader, output_dir=tmp_path)

    assert recorder.silence_end_threshold_ms == 800


def test_frame_recorder_timeout_marks_diagnostics(tmp_path):
    buffer = AudioFrameBuffer()
    reader = buffer.subscribe()
    recorder = FrameRecorder(reader, output_dir=tmp_path, min_duration_ms=20, max_duration_ms=30)
    recorder.start()
    buffer.publish(pcm())
    time.sleep(0.06)
    audio = recorder.stop()
    assert audio.diagnostics["timed_out"] is True


def test_frame_recorder_stops_after_configured_silence(tmp_path):
    buffer = AudioFrameBuffer()
    reader = buffer.subscribe()
    recorder = FrameRecorder(
        reader,
        output_dir=tmp_path,
        min_duration_ms=20,
        silence_end_threshold_ms=30,
        read_timeout_seconds=0.01,
    )
    recorder.start()
    buffer.publish(pcm(2000))
    time.sleep(0.08)

    assert recorder.completed is True
    audio = recorder.stop()

    assert audio.diagnostics["stop_reason"] == "silence_detected"
    assert audio.diagnostics["silence_detected_time"] is not None
    assert audio.diagnostics["recording_duration"] == audio.duration_ms
