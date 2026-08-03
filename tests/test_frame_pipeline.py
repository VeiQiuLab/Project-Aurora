from threading import Event

from modules.experience.audio.frame_pipeline import AudioFrameBuffer


def test_frame_buffer_fans_out_and_preserves_preroll():
    buffer = AudioFrameBuffer(max_duration_ms=1000)
    buffer.publish(b"old", timestamp=10.0)
    buffer.publish(b"recent", timestamp=10.8)
    vad_reader = buffer.subscribe(pre_roll_ms=500)
    recorder_reader = buffer.subscribe(pre_roll_ms=1000)

    assert vad_reader.read_frame(Event(), 0).data == b"recent"
    assert recorder_reader.read_frame(Event(), 0).data == b"old"
    assert recorder_reader.read_frame(Event(), 0).data == b"recent"


def test_frame_buffer_assigns_sequence_and_diagnostics():
    buffer = AudioFrameBuffer()
    frame = buffer.publish(b"pcm", sample_rate=44100, channels=1, diagnostics={"source": "fake"})
    assert frame.sequence == 1
    assert frame.sample_rate == 44100
    assert frame.diagnostics["source"] == "fake"
