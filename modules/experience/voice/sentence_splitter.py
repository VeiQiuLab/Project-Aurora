"""Deterministic incremental segmentation for streamed Voice text."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import re
import unicodedata
from time import monotonic


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    kind: str = "lexical"
    complete: bool = True

    def contains(self, index: int) -> bool:
        return self.start <= index < self.end


class SentenceSplitter:
    """Turn append-only text chunks into stable, ordered speech segments."""

    _HARD_BOUNDARIES = frozenset("。！？!?")
    _SOFT_BOUNDARIES = frozenset("；;：:，,")
    _CLOSERS = frozenset("”’\"'）)】]》〉」』")
    _OPEN_TO_CLOSE = {
        "“": "”",
        "‘": "’",
        "「": "」",
        "『": "』",
        "（": "）",
        "(": ")",
        "【": "】",
        "[": "]",
        "《": "》",
        "〈": "〉",
    }
    _COMMON_ABBREVIATION = re.compile(
        r"(?i)(?<![A-Za-z])(?:e\.g|i\.e|dr|mr|ms)\."
    )
    _INITIALISM = re.compile(r"(?<![A-Za-z])(?:[A-Za-z]\.){2,}")
    _SINGLE_INITIAL = re.compile(r"\b[A-Z]\.(?=\s*[A-Z])")
    _EMAIL = re.compile(
        r"(?i)(?<![A-Z0-9_.+-])[A-Z0-9._%+-]+@[A-Z0-9-]+(?:\.[A-Z0-9-]+)+"
    )
    # ASCII identifier look-behind rejects foohttps:// while allowing Chinese
    # prose to touch a scheme directly: 网址是https://example.com.
    _URL = re.compile(
        r"(?i)(?<![A-Z0-9_@])(?:https?://|www\.)"
        r"[^\s<>\[\]{}()，。！？；：\"',;!?]+"
    )
    _DOMAIN = re.compile(
        r"(?i)(?<![A-Z0-9_@.-])(?:[A-Z0-9-]+\.)+[A-Z]{2,}"
        r"(?:/[^\s<>\[\]{}()，。！？；：\"',;!?]*)?"
    )
    _URL_TERMINATORS = frozenset("<>[]{}()，。！？；：\"',;!?")

    def __init__(
        self,
        delimiters: str | None = None,
        *,
        minimum_length: int | None = None,
        max_wait_seconds: float = 0.5,
        min_soft_chars: int | None = None,
        target_chars: int = 32,
        max_chars: int = 64,
        absolute_max_chars: int = 512,
    ):
        if delimiters is not None and not delimiters:
            raise ValueError("delimiters must not be empty")
        if minimum_length is not None and min_soft_chars is not None:
            if int(minimum_length) != int(min_soft_chars):
                raise ValueError("minimum_length and min_soft_chars must agree")
        minimum = (
            min_soft_chars
            if min_soft_chars is not None
            else minimum_length if minimum_length is not None else 12
        )
        values = {
            "min_soft_chars": minimum,
            "target_chars": target_chars,
            "max_chars": max_chars,
            "absolute_max_chars": absolute_max_chars,
        }
        for name, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if target_chars < minimum:
            raise ValueError("target_chars must not be less than min_soft_chars")
        if max_chars < target_chars:
            raise ValueError("max_chars must not be less than target_chars")
        if absolute_max_chars < max_chars:
            raise ValueError("absolute_max_chars must not be less than max_chars")
        wait = float(max_wait_seconds)
        if not isfinite(wait) or wait <= 0:
            raise ValueError("max_wait_seconds must be finite and positive")

        self._custom_delimiters = frozenset(delimiters) if delimiters is not None else None
        self.min_soft_chars = int(minimum)
        self.minimum_length = self.min_soft_chars
        self.target_chars = int(target_chars)
        self.max_chars = int(max_chars)
        self.absolute_max_chars = int(absolute_max_chars)
        self.max_wait_seconds = wait
        self._buffer = ""
        self._pending_since_monotonic: float | None = None
        self._last_append_monotonic: float | None = None
        self._continuation_mode: str | None = None
        self._wrapper_stack: tuple[str, ...] = ()
        self._next_continuation_mode: str | None = None

    @property
    def pending_text(self) -> str:
        return self._buffer

    @property
    def pending_since_monotonic(self) -> float | None:
        return self._pending_since_monotonic

    @property
    def last_append_monotonic(self) -> float | None:
        return self._last_append_monotonic

    def feed(self, chunk: str) -> list[str]:
        """Append one chunk and return every newly stable segment."""

        if not isinstance(chunk, str):
            raise TypeError("chunk must be a string")
        if not chunk:
            return []

        now = monotonic()
        segments: list[str] = []
        if self.flush_due(now):
            pending = self._take_pending()
            if pending:
                segments.append(pending)

        if not self._buffer and not chunk.strip():
            return segments
        self._buffer += chunk
        self._last_append_monotonic = now
        if self._pending_since_monotonic is None and self._buffer.strip():
            self._pending_since_monotonic = now

        while self._buffer.strip():
            cut = self._next_cut()
            if cut is None:
                break
            segment = self._consume(cut)
            if segment:
                segments.append(segment)
        self._reset_timing_if_empty()
        return segments

    def flush(self) -> list[str]:
        """Emit remaining non-whitespace text once and reset all pending state."""

        segment = self._take_pending()
        return [segment] if segment else []

    def flush_due(self, now_monotonic: float | None = None) -> bool:
        """Return whether a caller may synchronously soft-flush a stalled buffer."""

        if (
            not self._buffer.strip()
            or self._last_append_monotonic is None
            or self._visible_length(self._buffer) < self.min_soft_chars
        ):
            return False
        lexical = self._protected_spans(self._buffer)
        wrappers = self._wrapper_spans(self._buffer, lexical)
        if any(
            not span.complete and span.end == len(self._buffer)
            for span in lexical + wrappers
        ):
            return False
        now = monotonic() if now_monotonic is None else float(now_monotonic)
        return now - self._last_append_monotonic >= self.max_wait_seconds

    def is_timeout_expired(self, now: float | None = None) -> bool:
        """Compatibility alias for the deterministic stall predicate."""

        return self.flush_due(now)

    def clear(self) -> None:
        """Discard pending text and every lexical/deadline state without emitting."""

        self._buffer = ""
        self._pending_since_monotonic = None
        self._last_append_monotonic = None
        self._continuation_mode = None
        self._wrapper_stack = ()
        self._next_continuation_mode = None

    def _next_cut(self) -> int | None:
        text = self._buffer
        lexical = self._protected_spans(text)
        wrappers = self._wrapper_spans(text, lexical)
        hard = self._find_hard_boundary(text, lexical)
        soft = self._find_soft_boundary(text, lexical)
        boundary = hard if soft is None or (hard is not None and hard <= soft) else soft
        if boundary is not None and self._visible_length(text[:boundary]) <= self.max_chars:
            return boundary
        if self._visible_length(text) > self.max_chars:
            return self._maximum_cut(text, lexical, wrappers)
        return boundary

    def _find_hard_boundary(self, text: str, lexical: tuple[_Span, ...]) -> int | None:
        index = 0
        while index < len(text):
            if self._is_protected(index, lexical):
                index += 1
                continue
            character = text[index]
            if self._custom_delimiters is not None:
                if character in self._custom_delimiters and not self._protected_period(
                    text, index, lexical
                ):
                    end = self._extend_closers(text, index + 1)
                    if self._boundary_closes_wrappers(text, index, end, lexical):
                        return end
                index += 1
                continue
            if character == "\n":
                if self._boundary_closes_wrappers(text, index, index + 1, lexical):
                    return index + 1
                index += 1
                continue
            if character == "…":
                end = index + 1
                while end < len(text) and text[end] == "…":
                    end += 1
                if end - index >= 2:
                    closed_end = self._extend_closers(text, end)
                    if self._boundary_closes_wrappers(text, index, closed_end, lexical):
                        return closed_end
                index = end
                continue
            if character == ".":
                end = index + 1
                while end < len(text) and text[end] == "." and not self._is_protected(
                    end, lexical
                ):
                    end += 1
                run = end - index
                if run >= 3:
                    closed_end = self._extend_closers(text, end)
                    if self._boundary_closes_wrappers(text, index, closed_end, lexical):
                        return closed_end
                elif run == 1 and not self._protected_period(text, index, lexical):
                    if index + 1 == len(text):
                        return None
                    closed_end = self._extend_closers(text, end)
                    if self._boundary_closes_wrappers(text, index, closed_end, lexical):
                        return closed_end
                index = end
                continue
            if character in self._HARD_BOUNDARIES:
                end = self._extend_closers(text, index + 1)
                if self._boundary_closes_wrappers(text, index, end, lexical):
                    return end
            index += 1
        return None

    def _find_soft_boundary(self, text: str, lexical: tuple[_Span, ...]) -> int | None:
        if self._custom_delimiters is not None:
            return None
        for index, character in enumerate(text):
            if character not in self._SOFT_BOUNDARIES or self._is_protected(index, lexical):
                continue
            if self._wrapper_stack_at(text, index, lexical):
                continue
            length = self._visible_length(text[: index + 1])
            threshold = self.target_chars if character in "，," else self.min_soft_chars
            if length >= threshold:
                return self._extend_closers(text, index + 1)
        return None

    def _maximum_cut(
        self,
        text: str,
        lexical: tuple[_Span, ...],
        wrappers: tuple[_Span, ...],
    ) -> int | None:
        limit = self._raw_index_for_visible_limit(text, self.max_chars)
        protected = lexical + wrappers
        containing = [
            span
            for span in protected
            if span.start < limit < span.end
            or (not span.complete and span.start < limit <= span.end)
        ]
        if containing:
            span = min(containing, key=lambda item: (item.start, -item.end))
            if span.start > 0:
                return span.start
            if self._visible_length(text) >= self.absolute_max_chars:
                cut = self._safe_unicode_cut(
                    text, self._raw_index_for_visible_limit(text, self.absolute_max_chars)
                )
                if span.kind != "wrapper":
                    self._next_continuation_mode = span.kind
                return cut
            if span.complete:
                return self._extend_completed_protected(text, span.end, lexical)
            return None

        candidates = [
            index + 1
            for index, character in enumerate(text[:limit])
            if character in self._SOFT_BOUNDARIES
            and not self._is_protected(index, protected)
        ]
        if candidates:
            return self._extend_closers(text, candidates[-1])
        whitespace = [
            index + 1
            for index, character in enumerate(text[:limit])
            if character.isspace() and not self._is_protected(index, protected)
        ]
        if whitespace:
            return whitespace[-1]
        return self._safe_unicode_cut(text, limit)

    def _consume(self, cut: int) -> str:
        lexical = self._protected_spans(self._buffer)
        wrappers_after_cut = self._wrapper_stack_at(self._buffer, cut, lexical)
        continuation = self._continuation_mode
        if continuation is not None:
            active = next(
                (
                    span
                    for span in lexical
                    if span.start == 0 and span.kind == continuation
                ),
                None,
            )
            if active is None or (active.complete and cut >= active.end):
                continuation = None
        if self._next_continuation_mode is not None:
            continuation = self._next_continuation_mode

        raw_segment = self._buffer[:cut]
        remainder = self._buffer[cut:]
        preserve_leading = bool(continuation or wrappers_after_cut)
        segment = raw_segment.strip()
        self._buffer = remainder if preserve_leading else remainder.lstrip()
        self._continuation_mode = continuation
        self._wrapper_stack = wrappers_after_cut
        self._next_continuation_mode = None
        if self._buffer.strip():
            self._pending_since_monotonic = self._last_append_monotonic
        else:
            self._reset_timing_if_empty()
        return segment

    def _take_pending(self) -> str:
        segment = self._buffer.strip()
        self.clear()
        return segment

    def _reset_timing_if_empty(self) -> None:
        if not self._buffer.strip():
            self._buffer = ""
            self._pending_since_monotonic = None
            self._last_append_monotonic = None
            self._next_continuation_mode = None

    def _protected_spans(self, text: str) -> tuple[_Span, ...]:
        spans: list[_Span] = []
        spans.extend(self._code_spans(text))
        spans.extend(self._markdown_spans(text))
        spans.extend(self._url_spans(text))
        for pattern in (
            self._EMAIL,
            self._DOMAIN,
            self._COMMON_ABBREVIATION,
            self._INITIALISM,
            self._SINGLE_INITIAL,
        ):
            spans.extend(
                _Span(match.start(), match.end()) for match in pattern.finditer(text)
            )
        spans.extend(
            _Span(index, index + 1)
            for index, character in enumerate(text)
            if character == "."
            and index > 0
            and index + 1 < len(text)
            and text[index - 1].isdigit()
            and text[index + 1].isdigit()
        )
        return tuple(sorted(spans, key=lambda span: (span.start, -span.end)))

    def _code_spans(self, text: str) -> list[_Span]:
        spans: list[_Span] = []
        index = 0
        if self._continuation_mode in {"fence", "inline"}:
            token = "```" if self._continuation_mode == "fence" else "`"
            closing = text.find(token)
            if closing < 0:
                return [_Span(0, len(text), self._continuation_mode, False)]
            end = closing + len(token)
            spans.append(_Span(0, end, self._continuation_mode, True))
            index = end
        while index < len(text):
            if text.startswith("```", index):
                closing = text.find("```", index + 3)
                complete = closing >= 0
                end = closing + 3 if complete else len(text)
                spans.append(_Span(index, end, "fence", complete))
                index = end
                continue
            if text[index] == "`":
                closing = text.find("`", index + 1)
                complete = closing >= 0
                end = closing + 1 if complete else len(text)
                spans.append(_Span(index, end, "inline", complete))
                index = end
                continue
            index += 1
        return spans

    def _markdown_spans(self, text: str) -> list[_Span]:
        spans: list[_Span] = []
        index = 0
        if self._continuation_mode == "markdown":
            closing = text.find(")")
            if closing < 0:
                return [_Span(0, len(text), "markdown", False)]
            spans.append(_Span(0, closing + 1, "markdown", True))
            index = closing + 1
        while index < len(text):
            start = text.find("[", index)
            if start < 0:
                break
            separator = text.find("](", start + 1)
            if separator < 0:
                break
            closing = text.find(")", separator + 2)
            complete = closing >= 0
            end = closing + 1 if complete else len(text)
            spans.append(_Span(start, end, "markdown", complete))
            index = end
        return spans

    def _url_spans(self, text: str) -> list[_Span]:
        spans: list[_Span] = []
        if self._continuation_mode == "url":
            end = self._url_end(text, 0)
            complete = end < len(text)
            spans.append(_Span(0, end, "url", complete))
        for pattern in (self._URL, self._DOMAIN):
            for match in pattern.finditer(text):
                end = match.end()
                while end > match.start() and text[end - 1] == "." and end < len(text):
                    end -= 1
                spans.append(_Span(match.start(), end, "url", end < len(text)))
        return spans

    def _wrapper_spans(
        self, text: str, lexical: tuple[_Span, ...]
    ) -> tuple[_Span, ...]:
        stack = list(self._wrapper_stack)
        start = 0 if stack else None
        spans: list[_Span] = []
        for index, character in enumerate(text):
            if self._is_protected(index, lexical):
                continue
            before = bool(stack)
            self._update_wrapper_stack(stack, text, index, character)
            if not before and stack:
                start = index
            elif before and not stack and start is not None:
                spans.append(_Span(start, index + 1, "wrapper", True))
                start = None
        if stack and start is not None:
            spans.append(_Span(start, len(text), "wrapper", False))
        return tuple(spans)

    def _wrapper_stack_at(
        self, text: str, end: int, lexical: tuple[_Span, ...]
    ) -> tuple[str, ...]:
        stack = list(self._wrapper_stack)
        for index, character in enumerate(text[:end]):
            if self._is_protected(index, lexical):
                continue
            self._update_wrapper_stack(stack, text, index, character)
        return tuple(stack)

    def _boundary_closes_wrappers(
        self,
        text: str,
        punctuation_start: int,
        boundary_end: int,
        lexical: tuple[_Span, ...],
    ) -> bool:
        before = self._wrapper_stack_at(text, punctuation_start, lexical)
        if not before:
            return True
        after = self._wrapper_stack_at(text, boundary_end, lexical)
        return not after

    @classmethod
    def _update_wrapper_stack(
        cls, stack: list[str], text: str, index: int, character: str
    ) -> None:
        if character in {'"', "'"}:
            if character == "'" and 0 < index < len(text) - 1:
                if text[index - 1].isalnum() and text[index + 1].isalnum():
                    return
            if stack and stack[-1] == character:
                stack.pop()
            else:
                stack.append(character)
            return
        closer = cls._OPEN_TO_CLOSE.get(character)
        if closer is not None:
            stack.append(closer)
        elif stack and character == stack[-1]:
            stack.pop()

    @classmethod
    def _url_end(cls, text: str, start: int) -> int:
        index = start
        while index < len(text):
            character = text[index]
            if character.isspace() or character in cls._URL_TERMINATORS:
                break
            index += 1
        return index

    def _protected_period(
        self, text: str, index: int, protected: tuple[_Span, ...]
    ) -> bool:
        if self._is_protected(index, protected):
            return True
        # Incremental Markdown can produce a completed link followed by a
        # domain/path suffix in the next chunk, for example
        # ``[example](https://example).com/path``.  Keep that joining period
        # lexical instead of treating it as a sentence boundary.
        if index + 1 < len(text) and text[index + 1].isalnum():
            if any(
                span.end == index and span.kind in {"markdown", "url"}
                for span in protected
            ):
                return True
        if 0 < index < len(text) - 1:
            if text[index - 1].isalpha() and text[index + 1].isalpha():
                token_start = index - 1
                while token_start > 0 and text[token_start - 1].isalpha():
                    token_start -= 1
                if index - token_start == 1:
                    return True
        return False

    def _extend_completed_protected(
        self, text: str, end: int, lexical: tuple[_Span, ...]
    ) -> int:
        if end >= len(text):
            return end
        character = text[end]
        if character in self._SOFT_BOUNDARIES:
            return self._extend_closers(text, end + 1)
        if character in self._HARD_BOUNDARIES or character == "\n":
            candidate = self._extend_closers(text, end + 1)
            if self._boundary_closes_wrappers(text, end, candidate, lexical):
                return candidate
        if character == "." and (
            end + 1 == len(text) or text[end + 1].isspace()
        ):
            return self._extend_closers(text, end + 1)
        if character in {"…", "."}:
            run_end = end + 1
            while run_end < len(text) and text[run_end] == character:
                run_end += 1
            required = 2 if character == "…" else 3
            if run_end - end >= required:
                candidate = self._extend_closers(text, run_end)
                if self._boundary_closes_wrappers(text, end, candidate, lexical):
                    return candidate
        return end

    @staticmethod
    def _is_protected(index: int, spans: tuple[_Span, ...]) -> bool:
        return any(span.contains(index) for span in spans)

    @classmethod
    def _extend_closers(cls, text: str, end: int) -> int:
        while end < len(text) and text[end] in cls._CLOSERS:
            end += 1
        return end

    @staticmethod
    def _visible_length(text: str) -> int:
        return len(text.strip())

    @staticmethod
    def _raw_index_for_visible_limit(text: str, limit: int) -> int:
        start = len(text) - len(text.lstrip())
        return min(start + limit, len(text))

    @staticmethod
    def _safe_unicode_cut(text: str, cut: int) -> int:
        cut = max(1, min(cut, len(text)))
        while cut < len(text):
            character = text[cut]
            if character == "\u200d" or unicodedata.combining(character):
                cut += 1
                continue
            if "VARIATION SELECTOR" in unicodedata.name(character, ""):
                cut += 1
                continue
            break
        return cut
