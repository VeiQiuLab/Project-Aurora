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
HIGH_VALUE_PATTERNS = [
    r"\balways\b|\bprefer\b|\bimportant\b|\bremember\b|\bdefault\b",
    r"总是|长期|重要|默认|记住|偏好|习惯"
]
LOW_VALUE_PATTERNS = [
    r"\bmaybe\b|\bprobably\b|\btry\b|\btest\b",
    r"可能|也许|试试|测试|随便"
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
        self.candidates_file = self.file_path.parent / "memory_candidates.json"
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _tokens(value):
        return set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", str(value or "").casefold()))

    @classmethod
    def _similarity(cls, first, second):
        left = cls._tokens(first)
        right = cls._tokens(second)
        if not left or not right:
            return 0.0
        return len(left.intersection(right)) / max(1, len(left.union(right)))

    @classmethod
    def _is_similar(cls, first, second, threshold=0.82):
        first_text = str(first or "").strip().casefold()
        second_text = str(second or "").strip().casefold()
        if not first_text or not second_text:
            return False
        return first_text == second_text or cls._similarity(first_text, second_text) >= threshold

    @staticmethod
    def _importance_value(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return {"high": 10.0, "normal": 5.0, "low": 1.0}.get(str(value).casefold(), 5.0)

    @staticmethod
    def _importance_label(score):
        if score >= 8:
            return "high"
        if score <= 2:
            return "low"
        return "normal"

    def score_candidate(self, candidate):
        if not isinstance(candidate, dict):
            return 0.0, "low"
        content = str(candidate.get("content", ""))
        try:
            score = float(candidate.get("score", 0)) * 10
        except (TypeError, ValueError):
            score = 0
        memory_type = str(candidate.get("type", "fact"))
        if memory_type == "instruction":
            score += 1.5
        elif memory_type == "preference":
            score += 1.0
        if any(re.search(pattern, content, re.IGNORECASE) for pattern in HIGH_VALUE_PATTERNS):
            score += 1.0
        if any(re.search(pattern, content, re.IGNORECASE) for pattern in LOW_VALUE_PATTERNS):
            score -= 2.0
        score = max(0.0, min(10.0, score))
        return score, self._importance_label(score)

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
        existing_content = [item.get("content", "") for item in memories]
        added = 0
        for item in items or []:
            normalized = self._normalize(item)
            if normalized["id"] in existing_ids:
                continue
            if any(self._is_similar(normalized.get("content", ""), content) for content in existing_content):
                continue
            memories.append(normalized)
            existing_ids.add(normalized["id"])
            existing_content.append(normalized.get("content", ""))
            added += 1
        self._write(memories)
        return added

    def extract_candidates(self, messages_or_text, min_score=0.75, source="chat"):
        base_candidates = MemoryExtractor(min_score=min_score).extract(messages_or_text)
        from modules.memory_intelligence import analyze_memory_candidates
        return analyze_memory_candidates(
            messages_or_text,
            base_candidates=base_candidates,
            min_score=min_score,
            source=source
        )

    def retrieve(self, prompt, max_results=5, min_importance=0):
        from modules.memory_retrieval import retrieve_memories
        return retrieve_memories(
            prompt,
            self.list_memories(),
            max_results=max_results,
            min_importance=min_importance
        )

    def format_context(self, memories, limit=1200):
        from modules.memory_retrieval import format_memory_context
        return format_memory_context(memories, limit=limit)

    def save_candidates(self, candidates, min_score=0.75):
        existing = {
            str(item.get("content", "")).strip().casefold()
            for item in self.list_memories()
        }
        existing_content = [item.get("content", "") for item in self.list_memories()]
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
            if any(self._is_similar(content, existing_item) for existing_item in existing_content):
                continue
            _quality, importance = self.score_candidate(candidate)
            saved.append(self.create(memory_type, content, importance))
            existing.add(key)
            existing_content.append(content)
        return saved

    def _normalize_candidate(self, item):
        now = self._now()
        normalized = dict(item) if isinstance(item, dict) else {}
        normalized.setdefault("id", uuid.uuid4().hex)
        normalized.setdefault("type", "fact")
        normalized.setdefault("content", "")
        normalized.setdefault("score", 0)
        normalized.setdefault("importance", "normal")
        normalized.setdefault("status", "pending")
        normalized.setdefault("source", "chat")
        normalized.setdefault("created_time", now)
        normalized.setdefault("updated_time", normalized["created_time"])
        if normalized["type"] not in MEMORY_TYPES:
            normalized["type"] = "fact"
        if normalized["status"] not in {"pending", "approved", "rejected"}:
            normalized["status"] = "pending"
        has_intelligence_importance = (
            "importance_score" in normalized
            and str(normalized.get("importance", "")).casefold() in {"low", "normal", "high"}
        )
        if not has_intelligence_importance:
            _quality, importance = self.score_candidate(normalized)
            normalized["importance"] = importance
        return normalized

    def list_candidates(self, status=None):
        if not self.candidates_file.exists():
            return []
        try:
            data = json.loads(self.candidates_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        candidates = [self._normalize_candidate(item) for item in data]
        if status:
            candidates = [item for item in candidates if item.get("status") == status]
        return candidates

    def queue_candidates(self, messages_or_text, source="chat", min_score=0.75):
        extracted = self.extract_candidates(messages_or_text, min_score=min_score, source=source)
        if not extracted:
            return []
        memories = {
            str(item.get("content", "")).strip().casefold()
            for item in self.list_memories()
        }
        memory_content = [item.get("content", "") for item in self.list_memories()]
        candidates = self.list_candidates()
        queued = {
            str(item.get("content", "")).strip().casefold()
            for item in candidates
            if item.get("status") == "pending"
        }
        queued_content = [
            item.get("content", "")
            for item in candidates
            if item.get("status") == "pending"
        ]
        added = []
        now = self._now()
        for item in extracted:
            content = str(item.get("content", "")).strip()
            key = content.casefold()
            if not content or key in memories or key in queued:
                continue
            if any(self._is_similar(content, existing) for existing in memory_content + queued_content):
                continue
            has_intelligence_importance = (
                "importance_score" in item
                and str(item.get("importance", "")).casefold() in {"low", "normal", "high"}
            )
            if has_intelligence_importance:
                quality = self._importance_value(item.get("importance_score", 0))
                importance = item.get("importance", "normal")
            else:
                quality, importance = self.score_candidate(item)
            candidate_data = dict(item)
            candidate_data.update({
                "type": item.get("type", "fact"),
                "content": content,
                "score": item.get("score", 0),
                "importance": importance,
                "status": "pending",
                "source": source,
                "created_time": now,
                "updated_time": now
            })
            candidate = self._normalize_candidate(candidate_data)
            if not has_intelligence_importance and quality < 2:
                candidate["importance"] = "low"
            candidates.append(candidate)
            queued.add(key)
            queued_content.append(content)
            added.append(candidate)
        if added:
            self._write_candidates(candidates)
        return added

    def approve_candidate(self, candidate_id):
        candidates = self.list_candidates()
        for item in candidates:
            if item.get("id") == candidate_id:
                saved = self.save_candidates([item], min_score=0)
                item["status"] = "approved"
                item["updated_time"] = self._now()
                self._write_candidates(candidates)
                return saved[0] if saved else None
        raise KeyError(candidate_id)

    def reject_candidate(self, candidate_id):
        candidates = self.list_candidates()
        for item in candidates:
            if item.get("id") == candidate_id:
                item["status"] = "rejected"
                item["updated_time"] = self._now()
                self._write_candidates(candidates)
                return item
        raise KeyError(candidate_id)

    def _write(self, memories):
        with self._lock:
            self.file_path.write_text(
                json.dumps(memories, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

    def _write_candidates(self, candidates):
        with self._lock:
            self.candidates_file.write_text(
                json.dumps(candidates, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
