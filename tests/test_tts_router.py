from threading import Event

import pytest

from modules.experience.voice.interfaces import TTSProvider
from modules.experience.voice.models import SpeechResult, TTSRequest, TTSResponse, VoiceOptions
from modules.experience.voice.tts_router import TTSRouter


class RecordingProvider(TTSProvider):
    def __init__(self):
        self.requests = []

    def synthesize(self, text, options=None, *, timeout_seconds=None, cancel_event=None):
        self.requests.append((text, options, timeout_seconds, cancel_event))
        return SpeechResult(audio_bytes=b"audio", mime_type="audio/mpeg")


def test_router_routes_legacy_call_to_default_provider():
    provider = RecordingProvider()
    router = TTSRouter({"test": provider}, default_provider="test")
    cancel_event = Event()

    result = router.synthesize(
        "hello",
        VoiceOptions(voice="aurora"),
        timeout_seconds=3,
        cancel_event=cancel_event,
    )

    assert result.audio_bytes == b"audio"
    assert provider.requests == [("hello", VoiceOptions(voice="aurora"), 3, cancel_event)]


def test_router_supports_explicit_provider_in_unified_request():
    first = RecordingProvider()
    second = RecordingProvider()
    router = TTSRouter({"first": first, "second": second}, default_provider="first")

    result = router.synthesize_request(TTSRequest(text="你好", provider="second"))

    assert isinstance(result, TTSResponse)
    assert not first.requests
    assert second.requests[0][0] == "你好"


def test_router_rejects_unimplemented_reserved_provider():
    router = TTSRouter({"edge_tts": RecordingProvider()}, default_provider="edge_tts")

    with pytest.raises(ValueError, match="reserved but not implemented"):
        router.provider_for("remote_cosyvoice")


def test_router_requires_registered_default_provider():
    with pytest.raises(ValueError, match="not registered"):
        TTSRouter({}, default_provider="edge_tts")
