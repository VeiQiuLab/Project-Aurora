"""Audio runtime boundaries for Aurora's Experience Layer."""

from .fake_audio import FakePlayback, FakeRecorder
from .playback import (
    AudioPlaybackController,
    PlaybackEvent,
    PlaybackEventType,
)
from .real_playback import RealPlaybackController
from .vad import (
    AudioFrameSource,
    FakeVAD,
    RMSVADAdapter,
    VADAdapter,
    VADAdapterError,
    VoiceActivityEvent,
    VoiceActivityType,
)
from .frame_pipeline import AudioFrame, AudioFrameBuffer, AudioFrameReader
from .ffmpeg_source import FFmpegAudioFrameSource, FakeFFmpegAudioFrameSource
from .device_discovery import (
    AudioDeviceDiscoveryError,
    DiscoveredAudioDevice,
    enumerate_dshow_audio_devices,
    resolve_voice_input_device,
)
from .frame_recorder import FrameRecorder
from .recorder import AudioRecorder, AudioRecorderError, FFmpegMicrophoneRecorder, MicrophoneRecorder

__all__ = [
    "AudioPlaybackController",
    "AudioRecorder",
    "AudioRecorderError",
    "FFmpegMicrophoneRecorder",
    "MicrophoneRecorder",
    "FakePlayback",
    "FakeRecorder",
    "PlaybackEvent",
    "PlaybackEventType",
    "RealPlaybackController",
    "AudioFrameSource",
    "FakeVAD",
    "RMSVADAdapter",
    "VADAdapter",
    "VADAdapterError",
    "VoiceActivityEvent",
    "VoiceActivityType",
    "AudioFrame",
    "AudioFrameBuffer",
    "AudioFrameReader",
    "FFmpegAudioFrameSource",
    "FakeFFmpegAudioFrameSource",
    "AudioDeviceDiscoveryError",
    "DiscoveredAudioDevice",
    "enumerate_dshow_audio_devices",
    "resolve_voice_input_device",
    "FrameRecorder",
]
