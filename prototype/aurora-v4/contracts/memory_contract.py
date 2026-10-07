"""V4-8B bounded, read-only inspection wire contract."""
import json
import re

ERRORS = {"MEMORY_READ_FAILED", "MEMORY_INVALID_DATA", "MEMORY_NOT_FOUND", "MEMORY_RECORD_TOO_LARGE"}
REQUEST_KEYS = {"collection", "record_id", "offset"}
RESPONSE_KEYS = {"collection", "operation", "records", "total", "offset", "source"}
FIELDS = {"id", "type", "importance", "enabled", "status", "created_time", "updated_time", "source", "score", "category", "confidence", "importance_score", "risk", "explanation", "source_detail", "analysis_version", "metadata"}


def validate_memory(kind, payload):
    if payload.get("collection") not in {"saved", "pending"} or type(payload.get("offset")) is not int or not 0 <= payload["offset"] <= 1_000_000:
        raise ValueError("Invalid Memory request.")
    if kind == "memory.read.request":
        if set(payload) != REQUEST_KEYS or (payload["record_id"] is not None and (not isinstance(payload["record_id"], str) or not re.fullmatch(r"[a-f0-9]{64}", payload["record_id"]))) or (payload["record_id"] is not None and payload["offset"] != 0):
            raise ValueError("Invalid Memory request.")
        return
    if kind != "memory.read.response" or set(payload) != RESPONSE_KEYS:
        raise ValueError("Invalid Memory response.")
    if payload["operation"] not in {"list", "detail"} or payload["source"] not in {"primary", "missing", "backup"} or type(payload["total"]) is not int or not 0 <= payload["total"] <= 1_000_000:
        raise ValueError("Invalid Memory response.")
    records = payload["records"]
    if not isinstance(records, list) or len(records) > 20 or (payload["operation"] == "detail" and (len(records) != 1 or payload["offset"] != 0)):
        raise ValueError("Invalid Memory records.")
    if payload["operation"] == "list" and len(records) != min(20, max(0, payload["total"] - payload["offset"])):
        raise ValueError("Invalid Memory page.")
    for record in records:
        if not isinstance(record, dict) or set(record) != {"inspection_id", "content", "preview", "fields"}:
            raise ValueError("Invalid Memory record.")
        if not isinstance(record["inspection_id"], str) or not re.fullmatch(r"[a-f0-9]{64}", record["inspection_id"]) or type(record["preview"]) is not bool or record["preview"] != (payload["operation"] == "list"):
            raise ValueError("Invalid Memory record.")
        if not isinstance(record["content"], str) or len(record["content"]) > (160 if record["preview"] else 32768):
            raise ValueError("Invalid Memory content.")
        if not isinstance(record["fields"], dict) or set(record["fields"]) - FIELDS or len(json.dumps(record["fields"], ensure_ascii=False, allow_nan=False).encode("utf-8")) > 16384:
            raise ValueError("Invalid Memory fields.")
