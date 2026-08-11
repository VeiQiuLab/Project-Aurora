from modules.experience.audio.recorder import (
    AudioRecorder,
    AudioRecorderError,
    FFmpegMicrophoneRecorder,
)
from modules.experience.subprocess_utils import with_hidden_console


def test_ffmpeg_recorder_contract():
    recorder = FFmpegMicrophoneRecorder(device_name="Sony microphone")
    assert isinstance(recorder, AudioRecorder)


def test_ffmpeg_recorder_reports_missing_dependency(monkeypatch):
    monkeypatch.setattr("modules.experience.audio.recorder.shutil.which", lambda _name: None)
    recorder = FFmpegMicrophoneRecorder(device_name="Sony microphone")

    try:
        recorder.start()
    except AudioRecorderError as error:
        assert error.code == "dependency_missing"
    else:
        raise AssertionError("expected missing ffmpeg diagnostic")


def test_ffmpeg_recorder_hides_windows_console(monkeypatch, tmp_path):
    captured = {}

    class FakeProcess:
        stdin = None
        returncode = None

    def fake_popen(*_args, **kwargs):
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr("modules.experience.audio.recorder.shutil.which", lambda name: name)
    recorder = FFmpegMicrophoneRecorder(
        device_name="Sony microphone",
        output_dir=tmp_path,
        popen_factory=fake_popen,
        warmup_seconds=0,
    )

    recorder.start()

    for key, value in with_hidden_console().items():
        assert captured[key] == value
