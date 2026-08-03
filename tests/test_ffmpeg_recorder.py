from modules.experience.audio.recorder import (
    AudioRecorder,
    AudioRecorderError,
    FFmpegMicrophoneRecorder,
)


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
