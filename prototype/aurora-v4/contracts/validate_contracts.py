"""Dependency-free executable checks for the Aurora IPC v1 specification.

This module is a contract test helper, not the production sidecar validator.
Runtime implementations should generate or validate types from the JSON Schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


PROTOCOL = "aurora-ipc"
VERSION = 1
COMMON_KEYS = {
    "protocol",
    "version",
    "type",
    "request_id",
    "session_id",
    "generation_id",
    "seq",
    "payload",
}
ID_KEYS = {"request_id", "session_id", "generation_id"}
STATES = {
    "STOPPED",
    "STARTING",
    "HANDSHAKING",
    "READY",
    "DEGRADED",
    "DISCONNECTED",
    "RESTARTING",
    "STOPPING",
}
TERMINAL_STATES = {"completed", "cancelled", "failed", "backend_lost", "rejected"}
ERROR_CODES = {
    "PROTOCOL_ERROR",
    "PROTOCOL_VERSION_MISMATCH",
    "AUTHENTICATION_FAILED",
    "INVALID_REQUEST",
    "PAYLOAD_TOO_LARGE",
    "BACKEND_NOT_READY",
    "BACKEND_LOST",
    "PROVIDER_UNAVAILABLE",
    "MODEL_UNAVAILABLE",
    "REQUEST_TIMEOUT",
    "REQUEST_CANCELLED",
    "INTERNAL_ERROR",
}


@dataclass(frozen=True)
class MessageRule:
    required: frozenset[str]
    forbidden: frozenset[str]
    payload_required: frozenset[str]
    payload_allowed: frozenset[str]


def _rule(
    *,
    required: Iterable[str] = (),
    forbidden: Iterable[str] = (),
    payload_required: Iterable[str] = (),
    payload_allowed: Iterable[str] = (),
) -> MessageRule:
    return MessageRule(
        frozenset(required),
        frozenset(forbidden),
        frozenset(payload_required),
        frozenset(payload_allowed),
    )


_NO_CONTEXT = {"session_id", "generation_id", "seq"}
_CHAT_IDS = {"request_id", "session_id", "generation_id"}
MESSAGE_RULES: dict[str, MessageRule] = {
    "hello": _rule(
        required={"request_id"},
        forbidden=_NO_CONTEXT,
        payload_required={"client", "supported_versions"},
        payload_allowed={"client", "supported_versions"},
    ),
    "hello_ack": _rule(
        required={"request_id"},
        forbidden=_NO_CONTEXT,
        payload_required={
            "selected_version",
            "sidecar_instance_id",
            "state",
            "capabilities",
            "limits",
        },
        payload_allowed={
            "selected_version",
            "sidecar_instance_id",
            "state",
            "capabilities",
            "limits",
        },
    ),
    "health.request": _rule(
        required={"request_id"}, forbidden=_NO_CONTEXT
    ),
    "health.response": _rule(
        required={"request_id"},
        forbidden=_NO_CONTEXT,
        payload_required={"state", "sidecar_instance_id", "capabilities", "limits"},
        payload_allowed={"state", "sidecar_instance_id", "capabilities", "limits"},
    ),
    "shutdown.request": _rule(
        required={"request_id"}, forbidden=_NO_CONTEXT
    ),
    "shutdown.ack": _rule(
        required={"request_id"},
        forbidden=_NO_CONTEXT,
        payload_required={"accepted"},
        payload_allowed={"accepted"},
    ),
    "chat.request": _rule(
        required=_CHAT_IDS,
        forbidden={"seq"},
        payload_required={"conversation_id", "input"},
        payload_allowed={"conversation_id", "input"},
    ),
    "chat.accepted": _rule(
        required=_CHAT_IDS,
        forbidden={"seq"},
        payload_required={"status"},
        payload_allowed={"status"},
    ),
    "chat.delta": _rule(
        required=_CHAT_IDS | {"seq"},
        payload_required={"delta"},
        payload_allowed={"delta"},
    ),
    "chat.completed": _rule(
        required=_CHAT_IDS,
        forbidden={"seq"},
        payload_required={"terminal_state"},
        payload_allowed={"terminal_state", "output_chars", "duration_ms", "error"},
    ),
    "chat.cancel.request": _rule(
        required=_CHAT_IDS,
        forbidden={"seq"},
        payload_required={"target_request_id"},
        payload_allowed={"target_request_id"},
    ),
    "chat.cancel.ack": _rule(
        required=_CHAT_IDS,
        forbidden={"seq"},
        payload_required={"target_request_id", "outcome"},
        payload_allowed={"target_request_id", "outcome"},
    ),
    "state.changed": _rule(
        forbidden={"request_id", "session_id", "generation_id", "seq"},
        payload_required={"state"},
        payload_allowed={"state", "reason"},
    ),
    "backend.warning": _rule(
        forbidden={"seq"},
        payload_required={"code", "message"},
        payload_allowed={"code", "message"},
    ),
    "error": _rule(
        forbidden={"seq"},
        payload_required={"code", "message", "retryable"},
        payload_allowed={"code", "message", "retryable"},
    ),
}


class ContractError(ValueError):
    """Raised when an object violates the frozen v1 contract."""


def _require_opaque_id(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ContractError(f"{field_name} must be a non-empty opaque string")


def _require_versions(value: Any, field_name: str) -> None:
    if (
        not isinstance(value, list)
        or not value
        or len(set(value)) != len(value)
        or any(not isinstance(item, int) or isinstance(item, bool) or item < 1 for item in value)
    ):
        raise ContractError(f"{field_name} must contain unique positive integers")


def _validate_limits(value: Any) -> None:
    expected = {
        "json_frame_max_bytes",
        "chat_input_max_bytes",
        "event_max_bytes",
        "binary_frame_max_bytes",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ContractError("limits must contain the four v1 limit fields")
    if any(
        not isinstance(item, int) or isinstance(item, bool) or item < 1
        for item in value.values()
    ):
        raise ContractError("all negotiated limits must be positive integers")


def _validate_capabilities(value: Any) -> None:
    expected = {"chat_streaming", "chat_cancel", "memory", "knowledge", "rag", "voice"}
    if not isinstance(value, dict) or not expected.issubset(value):
        raise ContractError("capabilities omit a required v1 field")
    if any(not isinstance(value[name], bool) for name in expected - {"voice"}):
        raise ContractError("core capability values must be booleans")
    voice = value["voice"]
    voice_expected = {
        "ipc",
        "edge_tts",
        "cosyvoice_remote",
        "cosyvoice_local",
        "streaming_pcm",
    }
    if not isinstance(voice, dict) or not voice_expected.issubset(voice):
        raise ContractError("voice capabilities omit a required v1 field")
    if any(not isinstance(voice[name], bool) for name in voice_expected):
        raise ContractError("voice capability values must be booleans")
    if voice["cosyvoice_local"] is not False:
        raise ContractError("Local CosyVoice is not implemented and must be false")
    if voice["ipc"] is not False or voice["streaming_pcm"] is not False:
        raise ContractError("Voice IPC and streaming PCM are reserved in v1")


def _validate_error(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"code", "message", "retryable"}:
        raise ContractError("error detail has invalid fields")
    if value["code"] not in ERROR_CODES:
        raise ContractError("unknown error code")
    if not isinstance(value["message"], str) or not value["message"] or len(value["message"]) > 512:
        raise ContractError("error message must be a bounded safe summary")
    if not isinstance(value["retryable"], bool):
        raise ContractError("error retryable must be boolean")


def validate_bootstrap(message: Mapping[str, Any]) -> None:
    required = {
        "protocol",
        "version",
        "type",
        "port",
        "pid",
        "supported_versions",
        "sidecar_instance_id",
    }
    if set(message) != required:
        raise ContractError("bootstrap.ready fields do not match v1")
    if message["protocol"] != PROTOCOL or message["version"] != VERSION:
        raise ContractError("bootstrap protocol/version mismatch")
    if message["type"] != "bootstrap.ready":
        raise ContractError("not a bootstrap.ready object")
    port = message["port"]
    pid = message["pid"]
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ContractError("bootstrap port is invalid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid < 1:
        raise ContractError("bootstrap PID is invalid")
    _require_versions(message["supported_versions"], "supported_versions")
    _require_opaque_id(message["sidecar_instance_id"], "sidecar_instance_id")


def validate_message(message: Mapping[str, Any]) -> None:
    if not isinstance(message, Mapping):
        raise ContractError("message must be an object")
    if message.get("type") == "bootstrap.ready":
        validate_bootstrap(message)
        return
    if set(message) - COMMON_KEYS:
        raise ContractError("message contains unknown top-level fields")
    for field_name in ("protocol", "version", "type", "payload"):
        if field_name not in message:
            raise ContractError(f"missing required field: {field_name}")
    if message["protocol"] != PROTOCOL:
        raise ContractError("protocol mismatch")
    if message["version"] != VERSION:
        raise ContractError("protocol version mismatch")
    message_type = message["type"]
    if message_type not in MESSAGE_RULES:
        raise ContractError("unknown message type")
    rule = MESSAGE_RULES[message_type]
    missing = rule.required - set(message)
    forbidden = rule.forbidden & set(message)
    if missing:
        raise ContractError(f"missing fields for {message_type}: {sorted(missing)}")
    if forbidden:
        raise ContractError(f"forbidden fields for {message_type}: {sorted(forbidden)}")
    for field_name in ID_KEYS & set(message):
        _require_opaque_id(message[field_name], field_name)
    if "seq" in message and (
        not isinstance(message["seq"], int)
        or isinstance(message["seq"], bool)
        or message["seq"] < 0
    ):
        raise ContractError("seq must be a non-negative integer")
    payload = message["payload"]
    if not isinstance(payload, dict):
        raise ContractError("payload must be an object")
    missing_payload = rule.payload_required - set(payload)
    extra_payload = set(payload) - rule.payload_allowed
    if missing_payload or extra_payload:
        raise ContractError(
            f"invalid payload fields for {message_type}: "
            f"missing={sorted(missing_payload)} extra={sorted(extra_payload)}"
        )
    _validate_payload(message_type, payload)


def _validate_payload(message_type: str, payload: Mapping[str, Any]) -> None:
    if message_type == "hello":
        if payload["client"] != "aurora-desktop":
            raise ContractError("hello client is invalid")
        _require_versions(payload["supported_versions"], "supported_versions")
    elif message_type == "hello_ack":
        if payload["selected_version"] != VERSION or payload["state"] not in {"READY", "DEGRADED"}:
            raise ContractError("hello_ack negotiation is invalid")
        _require_opaque_id(payload["sidecar_instance_id"], "sidecar_instance_id")
        _validate_capabilities(payload["capabilities"])
        _validate_limits(payload["limits"])
    elif message_type == "health.response":
        if payload["state"] not in STATES:
            raise ContractError("health state is invalid")
        _require_opaque_id(payload["sidecar_instance_id"], "sidecar_instance_id")
        _validate_capabilities(payload["capabilities"])
        _validate_limits(payload["limits"])
    elif message_type == "shutdown.ack" and payload["accepted"] is not True:
        raise ContractError("shutdown acknowledgement must be accepted")
    elif message_type == "chat.request":
        conversation_id = payload["conversation_id"]
        if conversation_id is not None:
            _require_opaque_id(conversation_id, "conversation_id")
        if not isinstance(payload["input"], str) or not payload["input"]:
            raise ContractError("chat input must be non-empty text")
    elif message_type == "chat.accepted" and payload["status"] != "accepted":
        raise ContractError("chat acceptance status is invalid")
    elif message_type == "chat.delta":
        if not isinstance(payload["delta"], str) or not payload["delta"]:
            raise ContractError("chat delta must be non-empty visible text")
    elif message_type == "chat.completed":
        terminal = payload["terminal_state"]
        if terminal not in TERMINAL_STATES:
            raise ContractError("unknown terminal state")
        needs_error = terminal in {"failed", "backend_lost", "rejected"}
        if needs_error != ("error" in payload):
            raise ContractError("terminal error detail does not match state")
        if "error" in payload:
            _validate_error(payload["error"])
        if "output_chars" in payload and (
            not isinstance(payload["output_chars"], int)
            or isinstance(payload["output_chars"], bool)
            or payload["output_chars"] < 0
        ):
            raise ContractError("output_chars must be a non-negative integer")
        if "duration_ms" in payload and (
            not isinstance(payload["duration_ms"], (int, float))
            or isinstance(payload["duration_ms"], bool)
            or payload["duration_ms"] < 0
        ):
            raise ContractError("duration_ms must be non-negative")
    elif message_type in {"chat.cancel.request", "chat.cancel.ack"}:
        _require_opaque_id(payload["target_request_id"], "target_request_id")
        if message_type == "chat.cancel.ack" and payload["outcome"] not in {
            "cancel_requested",
            "cancelled",
            "already_completed",
            "not_found",
        }:
            raise ContractError("cancel outcome is invalid")
    elif message_type == "state.changed":
        if payload["state"] not in STATES:
            raise ContractError("state.changed state is invalid")
    elif message_type == "backend.warning":
        if not all(isinstance(payload[name], str) and payload[name] for name in ("code", "message")):
            raise ContractError("backend warning must have code and message")
    elif message_type == "error":
        _validate_error(payload)


def negotiate_version(local_versions: Iterable[int], remote_versions: Iterable[int]) -> int:
    common = sorted(set(local_versions) & set(remote_versions), reverse=True)
    if not common:
        raise ContractError("PROTOCOL_VERSION_MISMATCH")
    return common[0]


@dataclass
class StreamContractValidator:
    """Check ordered deltas and one terminal state per generation."""

    next_sequence: dict[tuple[str, str], int] = field(default_factory=dict)
    terminal: dict[tuple[str, str], str] = field(default_factory=dict)

    def accept(self, message: Mapping[str, Any]) -> None:
        validate_message(message)
        message_type = message["type"]
        if message_type not in {"chat.accepted", "chat.delta", "chat.completed"}:
            return
        owner = (message["session_id"], message["generation_id"])
        if message_type == "chat.accepted":
            if owner in self.terminal or owner in self.next_sequence:
                raise ContractError("duplicate or stale chat.accepted")
            self.next_sequence[owner] = 0
            return
        if owner in self.terminal:
            raise ContractError("event arrived after terminal state")
        if message_type == "chat.delta":
            expected = self.next_sequence.setdefault(owner, 0)
            if message["seq"] != expected:
                raise ContractError(f"invalid sequence: expected {expected}")
            self.next_sequence[owner] = expected + 1
            return
        self.terminal[owner] = message["payload"]["terminal_state"]
        self.next_sequence.pop(owner, None)


def load_examples(path: Path | None = None) -> list[dict[str, Any]]:
    examples_path = path or Path(__file__).with_name("ipc-v1.examples.json")
    data = json.loads(examples_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ContractError("examples file must contain an array")
    return data


def validate_files() -> int:
    directory = Path(__file__).parent
    schema = json.loads((directory / "ipc-v1.schema.json").read_text(encoding="utf-8"))
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise ContractError("schema is not Draft 2020-12")
    examples = load_examples()
    stream = StreamContractValidator()
    for message in examples:
        stream.accept(message)
    return len(examples)


if __name__ == "__main__":
    count = validate_files()
    print(f"Aurora IPC v1 contract validation passed: {count} examples")
