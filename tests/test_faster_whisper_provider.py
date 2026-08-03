from types import SimpleNamespace

from modules.experience.voice.models import AudioInput
from modules.experience.voice.providers.faster_whisper import FasterWhisperProvider


def test_provider_initialization_is_lazy_and_configurable():
    provider = FasterWhisperProvider(
        model_size="tiny",
        device="cpu",
        compute_type="int8",
        beam_size=3,
    )

    assert provider.model_loaded is False
    assert provider.model_size == "tiny"
    assert provider.device == "cpu"
    assert provider.compute_type == "int8"
    assert provider.beam_size == 3


def test_file_input_is_transcribed_by_injected_model(tmp_path):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"fake audio")

    class FakeModel:
        def transcribe(self, path, *, language, beam_size):
            assert path == str(audio_path)
            assert language == "zh"
            assert beam_size == 5
            return iter(
                [SimpleNamespace(text=" 你好 "), SimpleNamespace(text="世界")]
            ), SimpleNamespace(language="zh", language_probability=0.91, duration=1.5)

    provider = FasterWhisperProvider(model=FakeModel())
    result = provider.transcribe(AudioInput(kind="file", path=str(audio_path), language_hint="zh"))

    assert result.text == "你好 世界"
    assert result.language == "zh"
    assert result.confidence == 0.91
    assert result.duration_ms == 1500
    assert result.diagnostics["success"] is True


def test_missing_dependency_returns_model_fallback_diagnostics(tmp_path):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"fake audio")
    provider = FasterWhisperProvider(
        model_loader=lambda *_args: (_ for _ in ()).throw(ImportError("missing faster-whisper"))
    )

    result = provider.transcribe(AudioInput(kind="file", path=str(audio_path)))

    assert result.text == ""
    assert result.diagnostics["success"] is False
    assert result.diagnostics["reason"] == "dependency_missing"


def test_provider_reports_input_and_transcription_errors(tmp_path):
    provider = FasterWhisperProvider(model=object())
    invalid = provider.transcribe(AudioInput(kind="bytes", data=b"audio"))
    missing = provider.transcribe(AudioInput(kind="file", path=str(tmp_path / "missing.wav")))

    assert invalid.diagnostics["reason"] == "unsupported_audio_input"
    assert missing.diagnostics["reason"] == "audio_file_not_found"
