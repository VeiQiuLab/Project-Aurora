"""Local JSON-backed long-term memory storage."""

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


MEMORY_TYPES = {"preference", "fact", "instruction"}
SENSITIVE_PATTERNS = [
    r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b",
    r"\b(?:\d[ -]*?){13,19}\b",
    r"\b\d{6,}\b",
    r"password|passcode|token|api[_ -]?key|secret|credential",
    r"身份证|护照|银行卡|密码|验证码|密钥|令牌"
]
TEMPORARY_PATTERNS = [
    r"\btoday\b|\btomorrow\b|\byesterday\b|\btonight\b|\bthis week\b",
    r"今天|明天|昨天|今晚|这周|临时|一次性"
]
EXTRACTION_RULES = [
    ("preference", 0.86, r"\bI (?:prefer|like|love|usually use|always use)\b(.+)"),
    ("preference", 0.82, r"\bMy preferred\b(.+)"),
    ("preference", 0.82, r"我(?:更喜欢|喜欢|偏好|通常用|一直用)(.+)"),
    ("instruction", 0.9, r"\bremember that\b(.+)"),
    ("instruction", 0.88, r"\bplease remember\b(.+)"),
    ("instruction", 0.88, r"请记住(.+)|记住(.+)"),
    ("fact", 0.78, r"\bmy (?:name|job|role|project|company|device)\b(.+)"),
    ("fact", 0.78, r"我的(?:名字|工作|角色|项目|公司|设备)(.+)")
]


class MemoryExtractor:
    """Rule-based candidate extractor for long-term memory."""

    def __init__(self, min_score=0.75):
        self.min_score = float(min_score)

    @staticmethod
    def _message_text(messages_or_text):
        if isinstance(messages_or_text, str):
            return messages_or_text
        lines = []
        for message in messages_or_text or []:
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = str(message.get("content", "")).strip()
            if content:
                lines.append(content)
        return "\n".join(lines)

    @staticmethod
    def _clean(value):
        text = re.sub(r"\s+", " ", str(value or "")).strip(" .。,:：;；")
        return text[:240]

    @staticmethod
    def _blocked(text):
        lowered = str(text or "").casefold()
        return any(re.search(pattern, lowered, re.IGNORECASE) for pattern in SENSITIVE_PATTERNS)

    @staticmethod
    def _temporary(text):
        lowered = str(text or "").casefold()
        return any(re.search(pattern, lowered, re.IGNORECASE) for pattern in TEMPORARY_PATTERNS)

    def extract(self, messages_or_text):
        text = self._message_text(messages_or_text)
        candidates = []
        seen = set()
        for raw_line in re.split(r"[\n\r]+", text):
            line = self._clean(raw_line)
            if not line or self._blocked(line) or self._temporary(line):
                continue
            for memory_type, score, pattern in EXTRACTION_RULES:
                match = re.search(pattern, line, re.IGNORECASE)
                if not match:
                    continue
                content = self._clean(" ".join(group for group in match.groups() if group) or line)
                if not content or self._blocked(content) or self._temporary(content):
                    continue
                key = (memory_type, content.casefold())
                if key in seen or score < self.min_score:
                    continue
                seen.add(key)
                candidates.append({
                    "type": memory_type,
                    "content": content,
                    "score": score,
                    "importance": "normal",
                    "source": "rule"
                })
        return candidates


class MemoryStore:
    """Manage manually curated memories without automatic chat analysis."""

    def __init__(self, file_path=None):
        root = Path(__file__).resolve().parent.parent
        if file_path:
            candidate = Path(file_path)
            self.file_path = candidate / "memories.json" if candidate.suffix.lower() != ".json" else candidate
        else:
            self.file_path = root / "data" / "memory" / "memories.json"
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _normalize(self, item):
        now = self._now()
        normalized = dict(item) if isinstance(item, dict) else {}
        normalized.setdefault("id", uuid.uuid4().hex)
        normalized.setdefault("type", "fact")
        normalized.setdefault("content", "")
        normalized.setdefault("created_time", normalized.get("created_at", now))
        normalized.setdefault("updated_time", normalized.get("updated_at", normalized["created_time"]))
        normalized.setdefault("importance", "normal")
        normalized.setdefault("enabled", True)
        return normalized

    def list_memories(self):
        if not self.file_path.exists():
            return []
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        normalized = [self._normalize(item) for item in data]
        if normalized != data:
            self._write(normalized)
        return normalized

    def create(self, memory_type, content, importance="normal"):
        now = self._now()
        item = {
            "id": uuid.uuid4().hex,
            "type": memory_type or "fact",
            "content": content.strip(),
            "created_time": now,
            "updated_time": now,
            "importance": importance or "normal",
            "enabled": True
        }
        memories = self.list_memories()
        memories.append(item)
        self._write(memories)
        return item

    def update(self, memory_id, memory_type, content, importance="normal"):
        memories = self.list_memories()
        for item in memories:
            if item.get("id") == memory_id:
                item.update({
                    "type": memory_type or "fact",
                    "content": content.strip(),
                    "updated_time": self._now(),
                    "importance": importance or "normal"
                })
                self._write(memories)
                return item
        raise KeyError(memory_id)

    def delete(self, memory_id):
        memories = [item for item in self.list_memories() if item.get("id") != memory_id]
        self._write(memories)

    def set_enabled(self, memory_id, enabled):
        memories = self.list_memories()
        for item in memories:
            if item.get("id") == memory_id:
                item["enabled"] = bool(enabled)
                item["updated_time"] = self._now()
                self._write(memories)
                return item
        raise KeyError(memory_id)

    def merge(self, items):
        memories = self.list_memories()
        existing_ids = {item.get("id") for item in memories}
        added = 0
        for item in items or []:
            normalized = self._normalize(item)
            if normalized["id"] in existing_ids:
                continue
            memories.append(normalized)
            existing_ids.add(normalized["id"])
            added += 1
        self._write(memories)
        return added

    def extract_candidates(self, messages_or_text, min_score=0.75):
        return MemoryExtractor(min_score=min_score).extract(messages_or_text)

    def save_candidates(self, candidates, min_score=0.75):
        existing = {
            str(item.get("content", "")).strip().casefold()
            for item in self.list_memories()
        }
        saved = []
        for candidate in candidates or []:
            if not isinstance(candidate, dict):
                continue
            try:
                score = float(candidate.get("score", 0))
            except (TypeError, ValueError):
                score = 0
            memory_type = str(candidate.get("type", "fact"))
            content = str(candidate.get("content", "")).strip()
            if memory_type not in MEMORY_TYPES or score < min_score or not content:
                continue
            key = content.casefold()
            if key in existing:
                continue
            saved.append(self.create(memory_type, content, candidate.get("importance", "normal")))
            existing.add(key)
        return saved

    def _write(self, memories):
        with self._lock:
            self.file_path.write_text(
                json.dumps(memories, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
