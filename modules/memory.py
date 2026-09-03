"""Local JSON-backed long-term memory storage."""

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from modules.app_paths import MEMORY_DIR


MEMORY_TYPES = {"preference", "fact", "instruction"}
MEMORY_METADATA_FIELDS = {
    "category",
    "confidence",
    "importance_score",
    "risk",
    "explanation",
    "source_detail",
    "analysis_version",
    "relation"
}
MEMORY_STATES = {"active", "superseded", "archived"}
LOGGER = logging.getLogger(__name__)
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
        if file_path:
            candidate = Path(file_path)
            self.file_path = candidate / "memories.json" if candidate.suffix.lower() != ".json" else candidate
        else:
            self.file_path = MEMORY_DIR / "memories.json"
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
        metadata = normalized.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            normalized["metadata"] = metadata
        metadata.setdefault("state", "active")
        metadata.setdefault("supersedes", None)
        metadata.setdefault("superseded_by", None)
        metadata.setdefault("valid_from", None)
        metadata.setdefault("valid_until", None)
        if metadata.get("state") not in MEMORY_STATES:
            metadata["state"] = "active"
        return normalized

    @staticmethod
    def _backup_path(path):
        return path.with_name(f"{path.name}.bak")

    @staticmethod
    def _read_json_list(path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as error:
            return None, error
        if not isinstance(data, list):
            return None, ValueError(f"{path.name} must contain a JSON list.")
        if not all(isinstance(item, dict) for item in data):
            return None, ValueError(f"{path.name} must contain JSON object records.")
        return data, None

    def _load_json_list(self, path):
        if not path.exists():
            return [], "missing"
        data, error = self._read_json_list(path)
        if error is None:
            return data, "primary"

        LOGGER.error("Memory storage read failed for %s: %s", path, error)
        backup_path = self._backup_path(path)
        if backup_path.exists():
            backup, backup_error = self._read_json_list(backup_path)
            if backup_error is None:
                LOGGER.warning("Memory storage recovered from %s", backup_path)
                return backup, "backup"
            LOGGER.error("Memory backup read failed for %s: %s", backup_path, backup_error)
        return [], "corrupt"

    @staticmethod
    def _replace_text(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("Could not remove temporary Memory file %s", temporary)

    def _atomic_write_json(self, path, records):
        if not isinstance(records, list):
            raise TypeError("Memory JSON payload must be a list.")
        payload = json.dumps(records, ensure_ascii=False, indent=2)
        with self._lock:
            if path.exists():
                current, current_error = self._read_json_list(path)
                backup_path = self._backup_path(path)
                if current_error is None:
                    current_payload = json.dumps(current, ensure_ascii=False, indent=2)
                    self._replace_text(backup_path, current_payload)
                else:
                    backup, backup_error = self._read_json_list(backup_path)
                    if backup_error is not None:
                        raise OSError(
                            f"Refusing to overwrite corrupt {path.name} without a valid backup."
                        ) from current_error
                    LOGGER.warning(
                        "Replacing corrupt %s while preserving valid backup %s",
                        path,
                        backup_path,
                    )
            self._replace_text(path, payload)

    @staticmethod
    def _validate_memories(memories):
        records = [item for item in memories if isinstance(item, dict)]
        if len(records) != len(memories):
            raise ValueError("Memory storage contains a non-object record.")
        by_id = {}
        for item in records:
            memory_id = str(item.get("id") or "")
            if not memory_id or memory_id in by_id:
                raise ValueError("Memory IDs must be non-empty and unique.")
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            state = metadata.get("state", "active")
            if state not in MEMORY_STATES:
                raise ValueError(f"Invalid Memory state: {state}")
            by_id[memory_id] = item

        for memory_id, item in by_id.items():
            metadata = item.get("metadata", {})
            supersedes = metadata.get("supersedes")
            superseded_by = metadata.get("superseded_by")
            if supersedes and str(supersedes) in by_id:
                previous = by_id[str(supersedes)]
                previous_metadata = previous.get("metadata", {})
                if (
                    previous_metadata.get("state") != "superseded"
                    or str(previous_metadata.get("superseded_by") or "") != memory_id
                ):
                    raise ValueError("Memory supersede links are inconsistent.")
            if superseded_by and str(superseded_by) in by_id:
                replacement = by_id[str(superseded_by)]
                replacement_metadata = replacement.get("metadata", {})
                if str(replacement_metadata.get("supersedes") or "") != memory_id:
                    raise ValueError("Memory superseded_by link is inconsistent.")

    def _new_memory(self, memory_type, content, importance="normal", metadata=None, *, now=None):
        created_time = now or self._now()
        memory_metadata = dict(metadata) if isinstance(metadata, dict) else {}
        memory_metadata.setdefault("state", "active")
        memory_metadata.setdefault("supersedes", None)
        memory_metadata.setdefault("superseded_by", None)
        memory_metadata.setdefault("valid_from", None)
        memory_metadata.setdefault("valid_until", None)
        return {
            "id": uuid.uuid4().hex,
            "type": memory_type or "fact",
            "content": str(content or "").strip(),
            "created_time": created_time,
            "updated_time": created_time,
            "importance": importance or "normal",
            "enabled": True,
            "metadata": memory_metadata,
        }

    def list_memories(self):
        data, source = self._load_json_list(self.file_path)
        if source == "corrupt":
            return []
        normalized = [self._normalize(item) for item in data]
        if source == "backup" or normalized != data:
            self._write(normalized)
        return normalized

    def create(self, memory_type, content, importance="normal", metadata=None):
        item = self._new_memory(memory_type, content, importance, metadata)
        memories = self.list_memories()
        memories.append(item)
        self._write(memories)
        return item

    def update(self, memory_id, memory_type, content, importance="normal"):
        memories = self.list_memories()
        for item in memories:
            if item.get("id") == memory_id:
                next_type = memory_type or "fact"
                next_content = content.strip()
                content_changed = str(item.get("content", "")) != next_content
                type_changed = str(item.get("type", "fact")) != next_type
                now = self._now()
                metadata = item.get("metadata")
                if isinstance(metadata, dict) and (content_changed or type_changed):
                    metadata["stale"] = True
                    metadata["stale_reason"] = "memory_updated"
                    metadata["stale_time"] = now
                item.update({
                    "type": next_type,
                    "content": next_content,
                    "updated_time": now,
                    "importance": importance or "normal"
                })
                self._write(memories)
                return item
        raise KeyError(memory_id)

    def delete(self, memory_id):
        memories = [item for item in self.list_memories() if item.get("id") != memory_id]
        self._write(memories)

    def archive(self, memory_id):
        memories = self.list_memories()
        for item in memories:
            if item.get("id") != memory_id:
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            if self._memory_state(item) == "archived":
                return item
            if self._memory_state(item) != "active":
                raise ValueError("Only active Memory can be archived.")
            archived_time = self._now()
            metadata["state"] = "archived"
            metadata["valid_until"] = archived_time
            item["metadata"] = metadata
            item["updated_time"] = archived_time
            self._write(memories)
            return item
        raise KeyError(memory_id)

    def restore(self, memory_id):
        memories = self.list_memories()
        for item in memories:
            if item.get("id") != memory_id:
                continue
            if self._memory_state(item) != "archived":
                raise ValueError("Only archived Memory can be restored.")
            restored_time = self._now()
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            metadata.update({
                "state": "active",
                "valid_from": restored_time,
                "valid_until": None,
            })
            item["metadata"] = metadata
            item["updated_time"] = restored_time
            self._write(memories)
            return item
        raise KeyError(memory_id)

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

    def retrieve(
        self,
        prompt,
        max_results=5,
        min_importance=0,
        min_relevance=0.35,
        confidence_default=0.5,
        ranking_weights=None,
    ):
        from modules.memory_retrieval import retrieve_memories
        return retrieve_memories(
            prompt,
            self.list_memories(),
            max_results=max_results,
            min_importance=min_importance,
            min_relevance=min_relevance,
            confidence_default=confidence_default,
            ranking_weights=ranking_weights,
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
            has_intelligence_importance = (
                "importance_score" in candidate
                and str(candidate.get("importance", "")).casefold() in {"low", "normal", "high"}
            )
            if has_intelligence_importance:
                importance = candidate.get("importance", "normal")
            else:
                _quality, importance = self.score_candidate(candidate)
            metadata = dict(candidate.get("metadata", {})) if isinstance(candidate.get("metadata"), dict) else {}
            metadata.update({
                key: candidate[key]
                for key in MEMORY_METADATA_FIELDS
                if key in candidate
            })
            saved.append(self.create(memory_type, content, importance, metadata=metadata))
            existing.add(key)
            existing_content.append(content)
        return saved

    def queue_candidate_records(self, candidates):
        """Persist already-evaluated records as pending candidates only."""

        existing_memories = {
            str(item.get("content", "")).strip().casefold()
            for item in self.list_memories()
        }
        pending = self.list_candidates(status="pending")
        pending_keys = {
            str(item.get("content", "")).strip().casefold()
            for item in pending
        }
        pending_content = [item.get("content", "") for item in pending]
        stored = []
        now = self._now()
        for raw_candidate in candidates or []:
            if not isinstance(raw_candidate, dict):
                continue
            candidate_data = dict(raw_candidate)
            content = str(candidate_data.get("content", "")).strip()
            memory_type = str(candidate_data.get("type", "fact"))
            key = content.casefold()
            if not content or memory_type not in MEMORY_TYPES:
                continue
            if key in existing_memories or key in pending_keys:
                continue
            relation = self._analyze_relation(candidate_data)
            if relation["type"] == "duplicate":
                continue
            if relation["type"] == "new" and any(self._is_similar(content, existing) for existing in pending_content):
                continue
            candidate_metadata = dict(candidate_data.get("metadata", {})) if isinstance(candidate_data.get("metadata"), dict) else {}
            candidate_metadata["relation"] = relation
            candidate_data.update({
                "type": memory_type,
                "content": content,
                "status": "pending",
                "source": candidate_data.get("source", "conversation"),
                "created_time": candidate_data.get("created_time", now),
                "updated_time": now,
                "metadata": candidate_metadata,
            })
            candidate = self._normalize_candidate(candidate_data)
            pending.append(candidate)
            pending_keys.add(key)
            pending_content.append(content)
            stored.append(candidate)
        if stored:
            self._write_candidates(pending)
        return stored

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
        data, source = self._load_json_list(self.candidates_file)
        if source == "corrupt":
            return []
        candidates = [self._normalize_candidate(item) for item in data]
        if source == "backup":
            self._write_candidates(candidates)
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
            relation = self._analyze_relation(item)
            if relation["type"] == "duplicate":
                continue
            if relation["type"] == "new" and any(self._is_similar(content, existing) for existing in memory_content + queued_content):
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
                "updated_time": now,
                "metadata": {
                    **(item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}),
                    "relation": relation,
                }
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
                if item.get("status") != "pending":
                    raise ValueError("Only pending Memory candidates can be approved.")
                relation = item.get("metadata", {}).get("relation", {}) if isinstance(item.get("metadata"), dict) else {}
                if relation.get("type") == "possible_update":
                    saved = self._approve_update_candidate(item, relation)
                else:
                    saved = self.save_candidates([item], min_score=0)
                item["status"] = "approved"
                item["updated_time"] = self._now()
                self._write_candidates(candidates)
                return saved[0] if saved else None
        raise KeyError(candidate_id)

    def _approve_update_candidate(self, candidate, relation):
        target_id = str(relation.get("target_memory_id") or "")
        memories = self.list_memories()
        target = next(
            (memory for memory in memories
             if str(memory.get("id")) == target_id
             and self._memory_state(memory) == "active"),
            None,
        )
        if target is None:
            return self.save_candidates([candidate], min_score=0)

        approval_time = self._now()
        metadata = dict(candidate.get("metadata", {})) if isinstance(candidate.get("metadata"), dict) else {}
        metadata.update({
            "state": "active",
            "supersedes": target["id"],
            "superseded_by": None,
            "valid_from": approval_time,
            "valid_until": None,
        })
        saved = self._new_memory(
            str(candidate.get("type", "fact")),
            str(candidate.get("content", "")),
            str(candidate.get("importance", "normal")),
            metadata=metadata,
            now=approval_time,
        )
        target_metadata = target.get("metadata") if isinstance(target.get("metadata"), dict) else {}
        target_metadata.update({
            "state": "superseded",
            "superseded_by": saved["id"],
            "valid_until": approval_time,
        })
        target["metadata"] = target_metadata
        target["updated_time"] = approval_time
        memories.append(saved)
        self._validate_memories(memories)
        self._write(memories)
        return [saved]

    @staticmethod
    def _memory_state(memory):
        metadata = memory.get("metadata") if isinstance(memory, dict) else {}
        state = metadata.get("state") if isinstance(metadata, dict) else None
        state = state or (memory.get("state") if isinstance(memory, dict) else None)
        return state if state in MEMORY_STATES else "active"

    @classmethod
    def _relation_category(cls, record):
        metadata = record.get("metadata") if isinstance(record, dict) else {}
        category = record.get("category") if isinstance(record, dict) else None
        if not category and isinstance(metadata, dict):
            category = metadata.get("category")
        if category:
            return str(category).casefold()
        content = str(record.get("content", "") if isinstance(record, dict) else "").casefold()
        if re.search(r"concise|detailed|summary|tone|style|language|回复|简洁|详细", content):
            return "communication_style"
        if re.search(r"project|repo|branch|architecture|version|项目|仓库|分支", content):
            return "project_information"
        if re.search(r"name|job|role|company|device|姓名|工作|角色|公司|设备", content):
            return "user_fact"
        return str(record.get("type", "fact")).casefold() if isinstance(record, dict) else "fact"

    def _analyze_relation(self, candidate):
        candidate_type = str(candidate.get("type", "fact")).casefold()
        candidate_category = self._relation_category(candidate)
        content = str(candidate.get("content", "")).strip()
        related = []
        for memory in self.list_memories():
            if self._memory_state(memory) != "active" or not memory.get("enabled", True):
                continue
            existing_content = str(memory.get("content", "")).strip()
            if content.casefold() == existing_content.casefold() or self._is_similar(content, existing_content):
                return {"type": "duplicate", "target_memory_id": memory.get("id"), "reason": "matching_memory_content"}
            if str(memory.get("type", "fact")).casefold() != candidate_type:
                continue
            existing_category = self._relation_category(memory)
            if existing_category == candidate_category:
                related.append(memory)

        if related:
            target = max(
                related,
                key=lambda memory: (
                    self._similarity(content, memory.get("content", "")),
                    str(memory.get("updated_time", "")),
                    str(memory.get("id", "")),
                ),
            )
            if candidate_category in {"communication_style", "project_information", "user_fact", "user_preference"}:
                return {"type": "possible_update", "target_memory_id": target.get("id"), "reason": "same_type_and_property_category"}
            return {"type": "possible_conflict", "target_memory_id": target.get("id"), "reason": "same_type_and_category"}
        return {"type": "new", "target_memory_id": None, "reason": "no_active_related_memory"}

    def reject_candidate(self, candidate_id):
        candidates = self.list_candidates()
        for item in candidates:
            if item.get("id") == candidate_id:
                if item.get("status") != "pending":
                    raise ValueError("Only pending Memory candidates can be rejected.")
                item["status"] = "rejected"
                item["updated_time"] = self._now()
                self._write_candidates(candidates)
                return item
        raise KeyError(candidate_id)

    def _write(self, memories):
        self._validate_memories(memories)
        self._atomic_write_json(self.file_path, memories)

    def _write_candidates(self, candidates):
        if not all(isinstance(item, dict) for item in candidates):
            raise ValueError("Memory candidate storage contains a non-object record.")
        self._atomic_write_json(self.candidates_file, candidates)
