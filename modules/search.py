"""Small, defensive local search helpers for Memory and Conversation data."""

import json
from pathlib import Path


def search_memories(memories, keyword="", memory_type=None, importance=None, enabled=None):
    query = str(keyword or "").strip().casefold()
    results = []
    for raw in memories or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item.setdefault("type", "fact")
        item.setdefault("importance", "normal")
        item.setdefault("enabled", True)
        searchable = f"{item.get('content', '')} {item.get('type', '')}".casefold()
        if query and query not in searchable:
            continue
        if memory_type and item.get("type") != memory_type:
            continue
        if importance and item.get("importance") != importance:
            continue
        item_enabled = item.get("enabled", True)
        if isinstance(item_enabled, str):
            item_enabled = item_enabled.strip().casefold() not in {"false", "0", "no"}
        if enabled is not None and bool(item_enabled) != bool(enabled):
            continue
        results.append(item)
    return results


def search_conversations(directory, keyword=""):
    query = str(keyword or "").strip().casefold()
    root = Path(directory)
    results = []
    for path in root.glob("*.json") if root.exists() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        messages = data.get("messages", [])
        message_text = " ".join(
            str(item.get("content", "")) for item in messages if isinstance(item, dict)
        )
        searchable = " ".join([
            str(data.get("title", "")),
            str(data.get("model", "")),
            message_text
        ]).casefold()
        if query and query not in searchable:
            continue
        created_time = data.get("created_time", data.get("created_at", ""))
        updated_time = data.get("updated_time", data.get("updated_at", ""))
        results.append({
            "id": str(data.get("id", path.stem)),
            "title": str(data.get("title", "New Conversation")),
            "model": str(data.get("model", "")),
            "created_time": str(created_time),
            "updated_time": str(updated_time),
            "created_at": str(created_time),
            "updated_at": str(updated_time)
        })
    return sorted(results, key=lambda item: item.get("updated_time", ""), reverse=True)
