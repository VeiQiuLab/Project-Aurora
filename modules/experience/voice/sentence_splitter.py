"""Incremental sentence splitting for streamed Voice text."""

from __future__ import annotations

from time import monotonic


class SentenceSplitter:
    """Turn streamed text chunks into complete, ordered sentences."""

    _DEFAULT_DELIMITERS = frozenset("。！？；.!?;\n")

    def __init__(
        self,
        delimiters: str | None = None,
        *,
        minimum_length: int = 8,
        max_wait_seconds: float = 1.5,
    ):
        value = self._DEFAULT_DELIMITERS if delimiters is None else frozenset(delimiters)
        if not value:
            raise ValueError("delimiters must not be empty")
        if minimum_length < 1:
            raise ValueError("minimum_length must be positive")
        if max_wait_seconds <= 0:
            raise ValueError("max_wait_seconds must be positive")
        self._delimiters = value
        self.minimum_length = int(minimum_length)
        self.max_wait_seconds = float(max_wait_seconds)
        self._buffer = ""
        self._buffer_started_at: float | None = None

    @property
    def pending_text(self) -> str:
        return self._buffer

    def feed(self, chunk: str) -> list[str]:
        """Append a chunk and emit complete sentences or an expired buffer."""

        if not isinstance(chunk, str):
            raise TypeError("chunk must be a string")
        if not chunk:
            return []

        sentences: list[str] = []
        if self.is_timeout_expired():
            expired = self._buffer.strip()
            self.clear()
            if expired:
                sentences.append(expired)

        self._buffer += chunk
        if self._buffer_started_at is None:
            self._buffer_started_at = monotonic()

        sentence_start = 0
        for index, character in enumerate(self._buffer):
            if character not in self._delimiters or self._is_decimal_point(index):
                continue
            sentence = self._buffer[sentence_start : index + 1].strip()
            if sentence and (len(sentence) >= self.minimum_length or character in "。！？.!?;\n"):
                sentences.append(sentence)
                sentence_start = index + 1

        self._buffer = self._buffer[sentence_start:]
        if not self._buffer:
            self._buffer_started_at = None
        return [sentence for sentence in sentences if sentence]

    def flush(self) -> list[str]:
        sentence = self._buffer.strip()
        self.clear()
        return [sentence] if sentence else []

    def is_timeout_expired(self, now: float | None = None) -> bool:
        if not self._buffer or self._buffer_started_at is None:
            return False
        current = monotonic() if now is None else now
        return current - self._buffer_started_at >= self.max_wait_seconds

    def clear(self) -> None:
        """Discard pending text when the active generation is interrupted."""

        self._buffer = ""
        self._buffer_started_at = None

    def _is_decimal_point(self, index: int) -> bool:
        if self._buffer[index] != ".":
            return False
        if index == 0 or index + 1 >= len(self._buffer):
            return False
        return self._buffer[index - 1].isdigit() and self._buffer[index + 1].isdigit()
