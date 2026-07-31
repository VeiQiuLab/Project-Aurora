"""Deterministic conversation analysis helpers for Project Aurora."""

from __future__ import annotations

import re
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


ANALYSIS_VERSION = "conversation_intelligence_v1"
VALID_ROLES = {"user", "assistant"}
STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "assistant",
    "but",
    "can",
    "chat",
    "conversation",
    "for",
    "from",
    "have",
    "help",
    "into",
    "memory",
    "message",
    "please",
    "project",
    "should",
    "that",
    "the",
    "this",
    "user",
    "with",
    "you",
}
EVENT_PATTERNS = [
    r"\bcompleted\b",
    r"\bimplemented\b",
    r"\bfixed\b",
    r"\breleased\b",
    r"\bdecided\b",
    r"\bapproved\b",
    r"\btagged\b",
    r"\bcommitted\b",
]


def analyze_conversation(messages, *, max_summary_chars=500) -> dict[str, Any]:
    """Analyze conversation messages without side effects."""

    return ConversationIntelligence(max_summary_chars=max_summary_chars).analyze(messages)


class ConversationIntelligence:
    """Produce deterministic conversation analysis records."""

    def __init__(self, *, max_summary_chars=500):
        try:
            self.max_summary_chars = max(0, int(max_summary_chars))
        except (TypeError, ValueError):
            self.max_summary_chars = 500

    def analyze(self, messages) -> dict[str, Any]:
        valid_messages = self._valid_messages(messages)
        user_messages = [item for item in valid_messages if item["role"] == "user"]
        assistant_messages = [item for item in valid_messages if item["role"] == "assistant"]

        return {
            "summary": self._summary(user_messages, assistant_messages),
            "topics": self._topics(valid_messages),
            "important_events": self._important_events(valid_messages),
            "memory_signals": [],
            "message_count": len(valid_messages),
            "user_message_count": len(user_messages),
            "assistant_message_count": len(assistant_messages),
            "analysis_version": ANALYSIS_VERSION,
            "analyzed_time": self._now(),
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _clean_text(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @classmethod
    def _valid_messages(cls, messages) -> list[dict[str, Any]]:
        records = []
        for index, message in enumerate(deepcopy(messages or [])):
            if not isinstance(message, dict):
                continue
            role = str(message.get("role", "")).strip()
            if role not in VALID_ROLES:
                continue
            content = cls._clean_text(message.get("content", ""))
            if not content:
                continue
            records.append({
                "index": index,
                "role": role,
                "content": content,
            })
        return records

    def _summary(self, user_messages, assistant_messages) -> str:
        source_messages = user_messages or assistant_messages
        if not source_messages or self.max_summary_chars <= 0:
            return ""
        parts = [item["content"] for item in source_messages[:3]]
        summary = " ".join(parts)
        return self._truncate(summary, self.max_summary_chars)

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        if limit <= 3:
            return value[:limit]
        return value[: limit - 3].rstrip() + "..."

    def _topics(self, messages) -> list[dict[str, Any]]:
        words = []
        for message in messages:
            words.extend(self._topic_words(message["content"]))
        if not words:
            return []
        counts = Counter(words)
        total = max(1, sum(counts.values()))
        topics = []
        for word, count in counts.most_common(5):
            confidence = min(1.0, max(0.1, count / total + 0.25))
            topics.append({
                "topic": word,
                "confidence": round(confidence, 3),
            })
        return topics

    @staticmethod
    def _topic_words(content: str) -> list[str]:
        words = []
        for match in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", content):
            word = match.strip("-_").casefold()
            if word and word not in STOPWORDS:
                words.append(word)
        return words

    def _important_events(self, messages) -> list[dict[str, Any]]:
        events = []
        for message in messages:
            content = message["content"]
            if not any(re.search(pattern, content, re.IGNORECASE) for pattern in EVENT_PATTERNS):
                continue
            events.append({
                "event": self._truncate(content, 180),
                "importance": "normal",
                "source": {
                    "message_indexes": [message["index"]],
                    "roles": [message["role"]],
                },
            })
        return events[:5]
