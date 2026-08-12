"""Per-turn timing context used by Voice diagnostic logging."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from time import monotonic


@dataclass
class VoiceTurnTrace:
    """Store monotonic markers without changing Voice Runtime behavior."""

    started_at: float = field(default_factory=monotonic)
    _marks: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def mark(self, name: str, *, first: bool = False) -> int:
        now = monotonic()
        with self._lock:
            if first and name in self._marks:
                timestamp = self._marks[name]
            else:
                self._marks[name] = now
                timestamp = now
        return int((timestamp - self.started_at) * 1000)

    def elapsed_ms(self, name: str) -> int | None:
        with self._lock:
            timestamp = self._marks.get(name)
        return None if timestamp is None else int((timestamp - self.started_at) * 1000)

    def now_elapsed_ms(self) -> int:
        return int((monotonic() - self.started_at) * 1000)

    def duration_ms(self, start: str, end: str) -> int | None:
        with self._lock:
            start_at = self._marks.get(start)
            end_at = self._marks.get(end)
        if start_at is None or end_at is None:
            return None
        return int((end_at - start_at) * 1000)
