from pathlib import Path

from modules.experience.voice.models import VoiceOptions
from modules.experience.voice.providers.edge_tts import EdgeTTSProvider


class FakeCommunicate:
    def __init__(self, text, *, voice, rate, error=None):
        self.text = text
        self.voice = voice
        self.rate = rate
        self.error = error

    async def save(self, path):
        if self.error is not None:
            raise self.error
        Path(path).write_bytes(b"fake-mp3")


def test_provider_initialization_is_lazy():
    provider = EdgeTTSProvider()

    assert provider.default_voice == "zh-CN-XiaoxiaoNeural"
    assert provider._communicate_factory is None


def test_fake_edge_generation_returns_mp3_path(tmp_path):
    calls = []

    def factory(text, *, voice, rate):
        calls.append((text, voice, rate))
        return FakeCommunicate(text, voice=voice, rate=rate)

    provider = EdgeTTSProvider(output_dir=tmp_path, communicate_factory=factory)
    result = provider.synthesize(
        "你好",
        VoiceOptions(language="zh_CN", rate=1.1, style="calm"),
    )

    assert result.audio_path is not None
    assert Path(result.audio_path).read_bytes() == b"fake-mp3"
    assert result.mime_type == "audio/mpeg"
    assert result.diagnostics["success"] is True
    assert result.diagnostics["warnings"]
    assert calls == [("你好", "zh-CN-XiaoxiaoNeural", "+10%")]


def test_network_or_generation_failure_returns_diagnostics_and_cleans_file(tmp_path):
    def factory(text, *, voice, rate):
        return FakeCommunicate(text, voice=voice, rate=rate, error=RuntimeError("network failed"))

    provider = EdgeTTSProvider(output_dir=tmp_path, communicate_factory=factory)
    result = provider.synthesize("hello")

    assert result.audio_path is None
    assert result.diagnostics["success"] is False
    assert result.diagnostics["reason"] == "generation_failed"
    assert list(tmp_path.glob("*.mp3")) == []


def test_empty_text_returns_fallback_without_creating_audio(tmp_path):
    provider = EdgeTTSProvider(output_dir=tmp_path, communicate_factory=FakeCommunicate)

    result = provider.synthesize("   ")

    assert result.audio_path is None
    assert result.diagnostics["reason"] == "empty_text"
    assert list(tmp_path.glob("*.mp3")) == []
