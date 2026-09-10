"""Replaceable voice interfaces for Aurora's Experience Layer."""

from .fake import FakeSpeechToTextProvider, FakeTextToSpeechProvider
from .interfaces import SpeechToTextProvider, TTSProvider, TextToSpeechProvider
from .models import AudioInput, SpeechResult, TTSRequest, TTSResponse, TranscriptionResult, VoiceOptions
from .tts_router import TTSRouter
from .session import VoiceSessionManager, VoiceSessionResult
from .sentence_splitter import SentenceSplitter
from .tts_queue import TTSQueue
from .providers.remote_cosyvoice import RemoteCosyVoiceProvider

__all__ = [
    "AudioInput",
    "FakeSpeechToTextProvider",
    "FakeTextToSpeechProvider",
    "SpeechResult",
    "SpeechToTextProvider",
    "TTSProvider",
    "TTSRequest",
    "TTSResponse",
    "TTSRouter",
    "RemoteCosyVoiceProvider",
    "TextToSpeechProvider",
    "TranscriptionResult",
    "VoiceOptions",
    "VoiceSessionManager",
    "VoiceSessionResult",
    "SentenceSplitter",
    "TTSQueue",
]
