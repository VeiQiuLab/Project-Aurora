"""Replaceable audio playback boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Callable, Mapping

from modules.experience.voice.models import SpeechResult


class PlaybackEventType(str, Enum):
    """Lifecycle events emitted by an audio playback implementation."""

    STARTED = "PlaybackStarted"
    COMPLETED = "PlaybackCompleted"
    STOPPED = "PlaybackStopped"
    FAILED = "PlaybackFailed"


@dataclass(frozen=True)
class PlaybackEvent:
    """Playback result notification; it does not mutate companion state."""

    event_type: PlaybackEventType
    speech: SpeechResult | None = None
    error: str = ""
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    timestamp: float = field(default_factory=time)


PlaybackCallback = Callable[[PlaybackEvent], None]


class AudioPlaybackController(ABC):
    """Play generated audio without knowing how it was synthesized."""

    @abstractmethod
    def play(self, speech: SpeechResult) -> None:
        """Start playback of a generated speech result."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the current playback, if any."""

    @abstractmethod
    def is_playing(self) -> bool:
        """Return whether audio is currently playing."""

    @abstractmethod
    def subscribe(self, callback: PlaybackCallback) -> PlaybackCallback:
        """Subscribe to playback lifecycle events."""

    @abstractmethod
    def unsubscribe(self, callback: PlaybackCallback) -> bool:
        """Unsubscribe from playback lifecycle events."""
