"""Local JSON conversation storage for Aurora Chat."""

import json
import hashlib
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from modules.app_paths import CONVERSATIONS_DIR


class ConversationManager:
    """Save, load, list, and delete chat conversations as JSON files."""

    def __init__(self, base_path=None):
        self.directory = Path(base_path) if base_path else CONVERSATIONS_DIR
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
    thread_factory=None,
    memory_store=None,
    min_message_count=2,
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
            saved = conversation_manager.save_conversation_intelligence(conversation_id, analysis)
            trigger = _trigger_conversation_memory(
                conversation_manager,
                conversation_id,
                captured_messages,
                analysis,
                saved,
                expected_updated_time=expected_updated_time,
                memory_store=memory_store,
                min_message_count=min_message_count,
            )
            if not trigger["diagnostics"].get("success", True) and logger:
                logger.error(trigger["diagnostics"].get("reason", "Conversation memory trigger failed."))
        except Exception as error:
            log_error(f"Conversation intelligence metadata save failed: {error}")

    thread = thread_factory(target=run_analysis, daemon=True)
    thread.start()
    return thread


def _trigger_conversation_memory(
    conversation_manager,
    conversation_id,
    messages,
    analysis,
    saved_conversation,
    *,
    expected_updated_time=None,
    memory_store=None,
    min_message_count=2,
):
    from modules.diagnostics import create_diagnostics

    signals = analysis.get("memory_signals", []) if isinstance(analysis, dict) else []
    metrics = {
        "conversation_id": str(conversation_id or ""),
        "triggered": False,
        "signals_count": len(signals) if isinstance(signals, list) else 0,
        "candidates_created": 0,
        "skipped_reason": "",
    }
    if not isinstance(analysis, dict) or not analysis.get("memory_signals"):
        metrics["skipped_reason"] = "empty_signals"
        return {"candidates": [], "diagnostics": create_diagnostics(
            stage="conversation_memory_trigger", metrics=metrics
        )}
    message_count = len(messages)
    try:
        minimum = max(0, int(min_message_count))
    except (TypeError, ValueError):
        minimum = 2
    if message_count < minimum:
        metrics["skipped_reason"] = "minimum_message_count"
        return {"candidates": [], "diagnostics": create_diagnostics(
            stage="conversation_memory_trigger", metrics=metrics
        )}

    current = conversation_manager.load(conversation_id)
    if len(current.get("messages", [])) != len(messages):
        metrics["skipped_reason"] = "stale_message_count"
        return {"candidates": [], "diagnostics": create_diagnostics(
            stage="conversation_memory_trigger", metrics=metrics
        )}
    fingerprint = _memory_trigger_fingerprint(
        expected_updated_time,
        analysis.get("analysis_version", ""),
        signals,
    )
    marker = current.get("metadata", {}).get("conversation_memory_trigger", {})
    if isinstance(marker, dict) and marker.get("source_fingerprint") == fingerprint:
        metrics["skipped_reason"] = "duplicate_fingerprint"
        return {"candidates": [], "diagnostics": create_diagnostics(
            stage="conversation_memory_trigger", metrics=metrics
        )}

    if memory_store is None:
        from modules.memory import MemoryStore
        memory_store = MemoryStore()
    from modules.conversation_memory_adapter import queue_conversation_memory_candidates

    result = queue_conversation_memory_candidates(
        memory_store,
        signals,
        conversation_id=conversation_id,
    )
    diagnostics = result.get("diagnostics", {})
    if not diagnostics.get("success", True):
        return {
            "candidates": [],
            "diagnostics": create_diagnostics(
                stage="conversation_memory_trigger",
                success=False,
                reason="Pending candidate pipeline failed.",
                warnings=diagnostics.get("warnings", []),
                metrics=metrics,
            ),
        }

    candidates = result.get("candidates", [])
    metrics["triggered"] = True
    metrics["candidates_created"] = len(candidates)
    conversation_manager.save_metadata(
        conversation_id,
        "conversation_memory_trigger",
        {
            "source_fingerprint": fingerprint,
            "analysis_version": analysis.get("analysis_version", ""),
            "analyzed_time": analysis.get("analyzed_time", ""),
            "candidate_count": len(candidates),
        },
    )
    return {
        "candidates": candidates,
        "diagnostics": create_diagnostics(
            stage="conversation_memory_trigger",
            metrics=metrics,
        ),
    }


def _memory_trigger_fingerprint(updated_time, analysis_version, signals):
    payload = json.dumps(
        {
            "updated_time": updated_time or "",
            "analysis_version": analysis_version or "",
            "signals": signals,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
