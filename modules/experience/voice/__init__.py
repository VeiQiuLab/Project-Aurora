"""Replaceable voice interfaces for Aurora's Experience Layer."""

from .fake import FakeSpeechToTextProvider, FakeTextToSpeechProvider
from .interfaces import SpeechToTextProvider, TextToSpeechProvider
from .models import AudioInput, SpeechResult, TranscriptionResult, VoiceOptions
from .session import VoiceSessionManager, VoiceSessionResult
from .sentence_splitter import SentenceSplitter
from .tts_queue import TTSQueue

__all__ = [
    "AudioInput",
    "FakeSpeechToTextProvider",
    "FakeTextToSpeechProvider",
    "SpeechResult",
    "SpeechToTextProvider",
    "TextToSpeechProvider",
    "TranscriptionResult",
    "VoiceOptions",
    "VoiceSessionManager",
    "VoiceSessionResult",
    "SentenceSplitter",
    "TTSQueue",
]
