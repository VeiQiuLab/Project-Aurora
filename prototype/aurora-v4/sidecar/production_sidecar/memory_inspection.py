"""Read-only projection of the existing context MemoryStore; no new storage."""
from __future__ import annotations

import hashlib
import json

PAGE_SIZE = 20
SUMMARY_FIELDS = {"id", "type", "importance", "enabled", "status", "created_time", "updated_time", "source"}
DETAIL_FIELDS = SUMMARY_FIELDS | {"score", "category", "confidence", "importance_score", "risk", "explanation", "source_detail", "analysis_version"}
METADATA_FIELDS = DETAIL_FIELDS | {"state", "supersedes", "superseded_by", "valid_from", "valid_until", "relation"}


class InspectionError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def inspection_id(record):
    # A content fingerprint is a read handle, not a persisted ID or schema field.
    # Changed/deleted records must be refreshed rather than showing stale detail.
    raw = json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def project(record, detail=False):
    content = record.get("content", "")
    if not isinstance(content, str):
        raise InspectionError("MEMORY_INVALID_DATA")
    fields = {key: value for key, value in record.items() if key in (DETAIL_FIELDS if detail else SUMMARY_FIELDS)}
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        selected = METADATA_FIELDS if detail else {"state"}
        fields["metadata"] = {key: value for key, value in metadata.items() if key in selected}
    # Keep IPC bounded and do not silently truncate single-record detail.
    if detail and len(content) > 32768:
        raise InspectionError("MEMORY_RECORD_TOO_LARGE")
    if not detail:
        fields = {key: value for key, value in fields.items()
                  if value is None or type(value) in {bool, int, float} or
                  (isinstance(value, str) and len(value) <= 256) or key == "metadata"}
    if len(json.dumps(fields, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 16384:
        raise InspectionError("MEMORY_RECORD_TOO_LARGE")
    return {"inspection_id": inspection_id(record), "content": content if detail else content[:160],
            "preview": not detail, "fields": fields}


def read_memory(store, payload):
    collection, record_id, offset = payload["collection"], payload["record_id"], payload["offset"]
    records, source = store.inspect_records(collection)
    if record_id is None:
        selected = [project(item) for item in records[offset:offset + PAGE_SIZE]]
    else:
        item = next((item for item in records if inspection_id(item) == record_id), None)
        if item is None:
            raise InspectionError("MEMORY_NOT_FOUND")
        selected = [project(item, detail=True)]
    return {"collection": collection, "operation": "list" if record_id is None else "detail",
            "records": selected, "total": len(records), "offset": offset, "source": source}
