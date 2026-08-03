from threading import Event

from modules.experience.audio.ffmpeg_source import FakeFFmpegAudioFrameSource
from modules.experience.audio.frame_pipeline import AudioFrameBuffer


def test_fake_ffmpeg_source_publishes_to_multiple_consumers():
    buffer = AudioFrameBuffer(max_duration_ms=1000)
    source = FakeFFmpegAudioFrameSource(buffer, [b"one", b"two"])
    vad_reader = buffer.subscribe()
    recorder_reader = buffer.subscribe(pre_roll_ms=1000)

    source.start()

    assert vad_reader.read_frame(Event(), 0).sequence == 1
    assert vad_reader.read_frame(Event(), 0).sequence == 2
    assert recorder_reader.read_frame(Event(), 0).data == b"one"
    assert recorder_reader.read_frame(Event(), 0).data == b"two"
    assert source.started == 1


def test_fake_ffmpeg_source_can_stop():
    source = FakeFFmpegAudioFrameSource(AudioFrameBuffer(), [])
    source.start()
    source.stop()
    assert source.stopped == 1
