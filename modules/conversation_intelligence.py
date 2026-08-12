"""Deterministic conversation analysis and lightweight title generation."""

from __future__ import annotations

import re
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


ANALYSIS_VERSION = "conversation_intelligence_v1"
VALID_ROLES = {"user", "assistant"}
STOPWORDS = {
    "about", "after", "again", "also", "and", "are", "assistant", "but", "can",
    "chat", "conversation", "for", "from", "have", "help", "into", "memory",
    "message", "please", "project", "should", "that", "the", "this", "user",
    "with", "you",
}
TITLE_STOPWORDS = {
    "aurora", "project", "please", "help", "want", "need", "could", "would",
    "tell", "about", "today", "what", "how", "why", "and", "the", "with",
}
TITLE_KEYWORDS = (
    "\u8bed\u97f3", "\u804a\u5929", "\u5bf9\u8bdd", "\u8bb0\u5fc6", "\u77e5\u8bc6", "\u6a21\u578b",
    "\u8bbe\u7f6e", "\u6d4b\u8bd5", "\u4efb\u52a1", "\u89c4\u5212", "\u9879\u76ee", "\u684c\u9762",
    "\u8bbe\u5907", "\u4f1a\u8bae", "\u5b66\u4e60", "\u5de5\u4f5c", "\u5b89\u88c5", "\u53d1\u5e03",
    "\u95ee\u9898", "\u65b9\u6848",
)
GENERIC_TITLES = {
    "\u5bf9\u8bdd\u5185\u5bb9\u56de\u987e", "\u666e\u901a\u5bf9\u8bdd", "\u804a\u5929\u5185\u5bb9", "\u7528\u6237\u95ee\u9898",
    "\u5bf9\u8bdd", "\u6807\u9898", "title", "conversation",
}
EVENT_PATTERNS = [
    r"\bcompleted\b", r"\bimplemented\b", r"\bfixed\b", r"\breleased\b",
    r"\bdecided\b", r"\bapproved\b", r"\btagged\b", r"\bcommitted\b",
]


def analyze_conversation(messages, *, max_summary_chars=500) -> dict[str, Any]:
    return ConversationIntelligence(max_summary_chars=max_summary_chars).analyze(messages)


def fallback_title(messages) -> str:
    """Return a neutral title while asynchronous analysis is pending."""
    return "\u65b0\u5bf9\u8bdd"


def _title_prompt(messages) -> str:
    user = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
    assistant = next((m.get("content", "") for m in messages if m.get("role") == "assistant"), "")
    return (
        "\u6839\u636e\u4e0b\u9762\u8fd9\u4e00\u8f6e\u5bf9\u8bdd\u751f\u6210\u4e00\u4e2a\u7b80\u77ed\u7684\u4e2d\u6587\u4f1a\u8bdd\u6807\u9898\u3002\n"
        "\u8981\u6c42\uff1a2\u52308\u4e2a\u6c49\u5b57\uff0c\u6700\u591a10\u4e2a\u5b57\uff1b\u6982\u62ec\u5b9e\u9645\u4e3b\u9898\uff1b\u4f18\u5148\u4f7f\u7528\u5177\u4f53\u4e3b\u9898\u540d\u8bcd\uff1b"
        "\u4e0d\u7167\u6284\u5b8c\u6574\u539f\u53e5\uff1b\u907f\u514d\u5173\u4e8e\u3001\u8ba8\u8bba\u3001\u5bf9\u8bdd\u3001\u5185\u5bb9\u3001\u95ee\u9898\u3001\u56de\u987e\u7b49\u5bbd\u6cdb\u8bcd\uff1b"
        "\u4e0d\u8981\u5f15\u53f7\u3001\u6807\u70b9\u3001\u89e3\u91ca\u6216\u6807\u9898\uff1a\uff0c\u53ea\u8fd4\u56de\u6807\u9898\u3002\n"
        f"\u7528\u6237\uff1a{user}\n\u52a9\u624b\uff1a{assistant}"
    )


def _clean_title(value: str) -> str:
    title = str(value or "").strip()
    title = re.sub(r"^(?:\u6807\u9898|title)\s*[:\uff1a]\s*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"[\"'\u201c\u201d\u2018\u2019\u3002.!\uff01?\uff1f:：,，、;；\s]+", "", title)
    if len(title) > 10 or not title or title in GENERIC_TITLES:
        return ""
    if len(title) == 1:
        return ""
    return title


def generate_title_summary(messages, model, *, llm_call=None) -> tuple[str, str]:
    """Return (title, source), using Ollama first and deterministic fallback second."""
    if llm_call is None:
        from modules.chat import chat_with_messages
        llm_call = lambda prompt: chat_with_messages(model, [{"role": "user", "content": prompt}], timeout=20)
    try:
        title = _clean_title(llm_call(_title_prompt(messages)))
        if title:
            return title, "llm"
    except Exception:
        pass
    title = ConversationIntelligence()._title_summary_from_messages(messages)
    if title:
        return title, "rule"
    return fallback_title(messages), "default"


class ConversationIntelligence:
    def __init__(self, *, max_summary_chars=500):
        try:
            self.max_summary_chars = max(0, int(max_summary_chars))
        except (TypeError, ValueError):
            self.max_summary_chars = 500

    def analyze(self, messages) -> dict[str, Any]:
        valid = self._valid_messages(messages)
        users = [item for item in valid if item["role"] == "user"]
        assistants = [item for item in valid if item["role"] == "assistant"]
        return {
            "summary": self._summary(users, assistants),
            "title_summary": self._title_summary(users, assistants),
            "topics": self._topics(valid),
            "important_events": self._important_events(valid),
            "memory_signals": [],
            "message_count": len(valid),
            "user_message_count": len(users),
            "assistant_message_count": len(assistants),
            "analysis_version": ANALYSIS_VERSION,
            "analyzed_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    @staticmethod
    def _clean_text(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @classmethod
    def _valid_messages(cls, messages):
        records = []
        for index, message in enumerate(deepcopy(messages or [])):
            if not isinstance(message, dict):
                continue
            role = str(message.get("role", "")).strip()
            content = cls._clean_text(message.get("content", ""))
            if role in VALID_ROLES and content:
                records.append({"index": index, "role": role, "content": content})
        return records

    def _summary(self, users, assistants):
        source = users or assistants
        return self._truncate(" ".join(item["content"] for item in source[:3]), self.max_summary_chars) if source else ""

    @classmethod
    def _title_summary(cls, users, assistants):
        return cls._title_summary_from_messages(users or assistants)

    @classmethod
    def _title_summary_from_messages(cls, messages):
        text = cls._clean_text(messages[0].get("content", "") if messages else "")
        if not text:
            return ""
        if re.search(r"\u5c0f\u8bf4.*\u4eba\u7269\u8bbe\u5b9a|\u4eba\u7269\u8bbe\u5b9a", text):
            return "\u4eba\u7269\u8bbe\u5b9a"
        if re.search(r"\u8bed\u97f3.*\u6253\u65ad|\u6253\u65ad.*\u8bed\u97f3", text):
            return "\u8bed\u97f3\u6253\u65ad"
        if re.search(r"minecraft", text, re.IGNORECASE) and re.search(r"\u5de5\u4f5c\u533a|\u89c4\u5212", text):
            return "Minecraft\u5de5\u4f5c\u533a"
        english = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)
        keywords = [key for key in TITLE_KEYWORDS if key in text]
        if keywords:
            title = "与".join(list(dict.fromkeys(keywords))[:2])
            if english and len(title) < 4:
                title = english[0] + title
            return title[:10]
        if english:
            return "".join(english[:2])[:10]
        return ""

    @staticmethod
    def _truncate(value, limit):
        if len(value) <= limit:
            return value
        return value[:max(0, limit - 3)].rstrip() + "..." if limit > 3 else value[:limit]

    def _topics(self, messages):
        words = []
        for message in messages:
            for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", message["content"]):
                word = word.strip("-_").casefold()
                if word and word not in STOPWORDS:
                    words.append(word)
        counts = Counter(words)
        total = max(1, sum(counts.values()))
        return [{"topic": word, "confidence": round(min(1.0, max(0.1, count / total + 0.25)), 3)} for word, count in counts.most_common(5)]

    def _important_events(self, messages):
        events = []
        for message in messages:
            if any(re.search(pattern, message["content"], re.IGNORECASE) for pattern in EVENT_PATTERNS):
                events.append({"event": self._truncate(message["content"], 180), "importance": "normal", "source": {"message_indexes": [message["index"]], "roles": [message["role"]]}})
        return events[:5]
