from threading import Event

import pytest

from modules.experience.voice import (
    AudioInput,
    FakeSpeechToTextProvider,
    FakeTextToSpeechProvider,
    SpeechResult,
    SpeechToTextProvider,
    StreamingSpeechResult,
    StreamingTTSProvider,
    TextToSpeechProvider,
    TranscriptionResult,
    VoiceOptions,
)


def test_data_models_preserve_provider_neutral_values():
    audio = AudioInput(kind="bytes", data=b"input", sample_rate=16000, language_hint="zh")
    transcription = TranscriptionResult(text="你好", language="zh", confidence=0.95)
    options = VoiceOptions(voice="aurora", rate=1.1, style="calm")
    speech = SpeechResult(audio_bytes=b"wav", mime_type="audio/wav")

    assert audio.data == b"input"
    assert transcription.confidence == 0.95
    assert options.style == "calm"
    assert speech.audio_bytes == b"wav"


def test_fake_stt_implements_contract_without_hardware():
    result = TranscriptionResult(text="test result", language="en")
    provider = FakeSpeechToTextProvider(result=result)
    audio = AudioInput(kind="file", path="sample.wav")

    actual = provider.transcribe(audio, timeout_seconds=1, cancel_event=Event())

    assert isinstance(provider, SpeechToTextProvider)
    assert actual == result
    assert provider.inputs == [audio]


def test_fake_tts_implements_contract_without_audio_output():
    result = SpeechResult(audio_bytes=b"fake")
    provider = FakeTextToSpeechProvider(result=result)
    options = VoiceOptions(voice="test")

    actual = provider.synthesize("hello", options, timeout_seconds=1, cancel_event=Event())

    assert isinstance(provider, TextToSpeechProvider)
    assert actual == result
    assert provider.requests == [("hello", options)]


def test_fake_providers_can_expose_deterministic_failures():
    stt = FakeSpeechToTextProvider(error=RuntimeError("stt unavailable"))
    tts = FakeTextToSpeechProvider(error=RuntimeError("tts unavailable"))

    with pytest.raises(RuntimeError, match="stt unavailable"):
        stt.transcribe(AudioInput(kind="bytes", data=b"input"))
    with pytest.raises(RuntimeError, match="tts unavailable"):
        tts.synthesize("hello")


def test_streaming_contract_is_independent_from_blocking_tts_and_playback():
    class Provider(StreamingTTSProvider):
        def synthesize_stream(self, text, options=None, **_kwargs):
            return StreamingSpeechResult(
                metadata={"sample_format": "s16le", "sample_rate": 24000},
                chunks=iter((b"\0\0",)),
            )

    result = Provider().synthesize_stream("hello")

    assert list(result.chunks) == [b"\0\0"]
    assert result.metadata["sample_rate"] == 24000
