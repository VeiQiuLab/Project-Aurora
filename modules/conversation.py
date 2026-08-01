"""Local JSON conversation storage for Aurora Chat."""

import json
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


class ConversationManager:
    """Save, load, list, and delete chat conversations as JSON files."""

    def __init__(self, base_path=None):
        project_root = Path(__file__).resolve().parent.parent
        self.directory = Path(base_path) if base_path else project_root / "data" / "conversations"
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _metadata_with_namespace(metadata, namespace, payload):
        base = deepcopy(metadata) if isinstance(metadata, dict) else {}
        if not namespace:
            return base
        base[str(namespace)] = deepcopy(payload) if isinstance(payload, dict) else {}
        return base

    def _normalize(self, data, fallback_id):
        now = self._now()
        normalized = dict(data) if isinstance(data, dict) else {}
        normalized.setdefault("id", fallback_id)
        normalized.setdefault("title", "New Conversation")
        normalized.setdefault("model", "")
        normalized.setdefault("created_time", normalized.get("created_at", now))
        normalized.setdefault("updated_time", normalized.get("updated_at", normalized["created_time"]))
        normalized.setdefault("messages", [])
        normalized.setdefault("metadata", {})
        if not isinstance(normalized.get("metadata"), dict):
            normalized["metadata"] = {}
        normalized["created_at"] = normalized["created_time"]
        normalized["updated_at"] = normalized["updated_time"]
        return normalized

    def list_conversations(self):
        records = []
        with self._lock:
            paths = list(self.directory.glob("*.json"))
        for path in paths:
            try:
                data = self._normalize(json.loads(path.read_text(encoding="utf-8")), path.stem)
                records.append({
                    "id": str(data["id"]),
                    "title": str(data["title"]),
                    "created_at": str(data.get("created_at", "")),
                    "updated_at": str(data.get("updated_at", "")),
                    "created_time": str(data.get("created_time", "")),
                    "updated_time": str(data.get("updated_time", "")),
                    "model": str(data.get("model", "")),
                    "metadata": data.get("metadata", {})
                })
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        return sorted(records, key=lambda item: item.get("updated_at", ""), reverse=True)

    def save(self, conversation_id, model, messages, title=None, created_at=None, metadata=None):
        conversation_id = conversation_id or uuid.uuid4().hex
        path = self.directory / f"{conversation_id}.json"
        now = self._now()
        existing_metadata = {}
        if created_at is None and path.exists():
            try:
                existing = self._normalize(json.loads(path.read_text(encoding="utf-8")), conversation_id)
                created_at = existing.get("created_time")
                existing_metadata = existing.get("metadata", {})
            except (OSError, json.JSONDecodeError, TypeError):
                created_at = None
        elif path.exists():
            try:
                existing = self._normalize(json.loads(path.read_text(encoding="utf-8")), conversation_id)
                existing_metadata = existing.get("metadata", {})
            except (OSError, json.JSONDecodeError, TypeError):
                existing_metadata = {}
        if metadata is None:
            metadata = existing_metadata
        elif not isinstance(metadata, dict):
            metadata = {}
        data = {
            "id": conversation_id,
            "title": title or "New Conversation",
            "created_at": created_at or now,
            "updated_at": now,
            "created_time": created_at or now,
            "updated_time": now,
            "model": model or "",
            "messages": messages,
            "metadata": metadata
        }
        with self._lock:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._normalize(data, conversation_id)

    def load(self, conversation_id):
        path = self.directory / f"{conversation_id}.json"
        data = self._normalize(json.loads(path.read_text(encoding="utf-8")), conversation_id)
        return data

    def save_metadata(self, conversation_id, namespace, payload):
        path = self.directory / f"{conversation_id}.json"
        with self._lock:
            data = self._normalize(json.loads(path.read_text(encoding="utf-8")), conversation_id)
            data["metadata"] = self._metadata_with_namespace(data.get("metadata", {}), namespace, payload)
            data["updated_at"] = self._now()
            data["updated_time"] = data["updated_at"]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._normalize(data, conversation_id)

    def save_conversation_intelligence(self, conversation_id, analysis):
        return self.save_metadata(conversation_id, "conversation_intelligence", analysis)

    def rename(self, conversation_id, title):
        path = self.directory / f"{conversation_id}.json"
        with self._lock:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["title"] = title.strip() or "New Conversation"
            data["updated_at"] = self._now()
            data["updated_time"] = data["updated_at"]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    def delete(self, conversation_id):
        path = self.directory / f"{conversation_id}.json"
        with self._lock:
            path.unlink(missing_ok=True)


def schedule_conversation_intelligence(
    conversation_manager,
    conversation_id,
    messages,
    *,
    expected_updated_time=None,
    logger=None,
    analyzer=None,
    thread_factory=None
):
    captured_messages = deepcopy(messages or [])
    expected_message_count = len(captured_messages)
    thread_factory = thread_factory or threading.Thread

    def log_error(message):
        if logger:
            try:
                logger.error(message)
            except Exception:
                pass

    def run_analysis():
        try:
            if analyzer is None:
                from modules.conversation_intelligence import analyze_conversation
                analysis = analyze_conversation(captured_messages)
            else:
                analysis = analyzer(captured_messages)
        except Exception as error:
            log_error(f"Conversation intelligence analysis failed: {error}")
            return

        try:
            current = conversation_manager.load(conversation_id)
            if len(current.get("messages", [])) != expected_message_count:
                return
            if expected_updated_time and current.get("updated_time") != expected_updated_time:
                return
            conversation_manager.save_conversation_intelligence(conversation_id, analysis)
        except Exception as error:
            log_error(f"Conversation intelligence metadata save failed: {error}")

    thread = thread_factory(target=run_analysis, daemon=True)
    thread.start()
    return thread
