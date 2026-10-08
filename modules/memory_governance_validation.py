"""Shared bounded request validation; no filesystem paths or batch operations."""
import re

REQUEST_KEYS = {"operation_id", "action", "id", "expected_version", "content", "confirmed"}
RESPONSE_KEYS = {"operation_id", "action", "id", "status", "saved_id"}
ERRORS = {"MEMORY_CONFLICT", "MEMORY_WRITE_FAILED", "MEMORY_RECOVERY_REQUIRED", "MEMORY_INVALID_EDIT", "MEMORY_INVALID_REQUEST"}


def validate_request(request):
    if not isinstance(request, dict) or set(request) != REQUEST_KEYS:
        raise ValueError("MEMORY_INVALID_REQUEST")
    if not isinstance(request["action"], str) or request["action"] not in {"approve", "reject", "edit", "delete"}:
        raise ValueError("MEMORY_INVALID_REQUEST")
    for key, pattern in [("operation_id", r"[a-zA-Z0-9-]{1,128}"), ("id", r"[a-zA-Z0-9_-]{1,128}"), ("expected_version", r"[a-f0-9]{64}")]:
        if not isinstance(request[key], str) or not re.fullmatch(pattern, request[key]):
            raise ValueError("MEMORY_INVALID_REQUEST")
    if type(request["confirmed"]) is not bool or (request["action"] == "delete" and not request["confirmed"]):
        raise ValueError("MEMORY_INVALID_REQUEST")
    if request["action"] == "edit":
        if not isinstance(request["content"], str) or not request["content"].strip() or len(request["content"]) > 32768:
            raise ValueError("MEMORY_INVALID_EDIT")
    elif request["content"] is not None:
        raise ValueError("MEMORY_INVALID_REQUEST")


def validate_result(result):
    if not isinstance(result, dict) or set(result) != RESPONSE_KEYS or result["status"] != "completed":
        raise ValueError("Invalid Memory operation result")
    validate_request({key: result[key] for key in ("operation_id", "action", "id")} | {
        "expected_version": "0" * 64, "content": "validated" if result["action"] == "edit" else None, "confirmed": True})
    if result["saved_id"] is not None and (not isinstance(result["saved_id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", result["saved_id"])):
        raise ValueError("Invalid Memory result identity")
