"""Replaceable voice interfaces for Aurora's Experience Layer."""

from .fake import FakeSpeechToTextProvider, FakeTextToSpeechProvider
from .interfaces import SpeechToTextProvider, StreamingTTSProvider, TTSProvider, TextToSpeechProvider
from .models import (
    AudioInput,
    SpeechSegment,
    SpeechResult,
    StreamingSpeechResult,
    TTSRequest,
    TTSResponse,
    TranscriptionResult,
    VoiceOptions,
)
from .tts_router import TTSRouter
from .session import VoiceSessionManager, VoiceSessionResult
from .sentence_splitter import SentenceSplitter
from .tts_queue import TTSQueue
from .providers.remote_cosyvoice import RemoteCosyVoiceProvider, StreamingSynthesisError

__all__ = [
    "AudioInput",
    "FakeSpeechToTextProvider",
    "FakeTextToSpeechProvider",
    "SpeechSegment",
    "SpeechResult",
    "SpeechToTextProvider",
    "StreamingSpeechResult",
    "StreamingTTSProvider",
    "TTSProvider",
    "TTSRequest",
    "TTSResponse",
    "TTSRouter",
    "RemoteCosyVoiceProvider",
    "StreamingSynthesisError",
    "TextToSpeechProvider",
    "TranscriptionResult",
    "VoiceOptions",
    "VoiceSessionManager",
    "VoiceSessionResult",
    "SentenceSplitter",
    "TTSQueue",
]
