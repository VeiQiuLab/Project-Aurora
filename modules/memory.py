"""Local JSON-backed long-term memory storage."""

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


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

    def _write(self, memories):
        with self._lock:
            self.file_path.write_text(
                json.dumps(memories, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
