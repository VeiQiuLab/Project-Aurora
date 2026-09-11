"""Aurora PCM stream version 1 framing and incremental validation."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any


CONTENT_TYPE = "application/vnd.aurora.pcm-stream; version=1"
PROTOCOL_VERSION = 1
MAX_FRAME_PAYLOAD = 64 * 1024
_HEADER = struct.Struct(">cI")
_FRAME_TYPES = {b"M", b"A", b"E", b"X"}


class StreamProtocolError(ValueError):
    """The framed stream violates the Aurora version 1 contract."""


@dataclass(frozen=True)
class StreamFrame:
    frame_type: str
    payload: bytes
    data: dict[str, Any] | None = None


def encode_frame(frame_type: str, payload: bytes | bytearray | memoryview) -> bytes:
    try:
        encoded_type = frame_type.encode("ascii")
    except (AttributeError, UnicodeEncodeError) as error:
        raise StreamProtocolError("frame type must be one ASCII character") from error
    if encoded_type not in _FRAME_TYPES:
        raise StreamProtocolError("unknown frame type")
    body = bytes(payload)
    if len(body) > MAX_FRAME_PAYLOAD:
        raise StreamProtocolError("frame payload exceeds 64 KiB")
    return _HEADER.pack(encoded_type, len(body)) + body


def encode_json_frame(frame_type: str, payload: dict[str, Any]) -> bytes:
    return encode_frame(
        frame_type,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    )


def metadata_payload(*, sample_rate: int, channels: int = 1) -> dict[str, Any]:
    return {
        "protocol": PROTOCOL_VERSION,
        "sample_format": "s16le",
        "bits_per_sample": 16,
        "sample_rate": int(sample_rate),
        "channels": int(channels),
        "interleaved": True,
    }


class StreamFrameDecoder:
    """Decode frames across arbitrary transport reads and enforce ordering."""

    def __init__(self, *, max_payload: int = MAX_FRAME_PAYLOAD) -> None:
        self.max_payload = min(max(int(max_payload), 1), MAX_FRAME_PAYLOAD)
        self._buffer = bytearray()
        self.metadata: dict[str, Any] | None = None
        self.terminal_type: str | None = None
        self.audio_frames = 0
        self.audio_bytes = 0
        self._pending_length: int | None = None

    def feed(self, data: bytes | bytearray | memoryview) -> list[StreamFrame]:
        if self.terminal_type is not None and data:
            raise StreamProtocolError("data received after terminal frame")
        self._buffer.extend(data)
        frames: list[StreamFrame] = []
        while True:
            if self._pending_length is None:
                if len(self._buffer) < _HEADER.size:
                    break
                encoded_type, payload_length = _HEADER.unpack(self._buffer[: _HEADER.size])
                del self._buffer[: _HEADER.size]
                if encoded_type not in _FRAME_TYPES:
                    raise StreamProtocolError("unknown frame type")
                if payload_length > self.max_payload:
                    raise StreamProtocolError("frame payload exceeds 64 KiB")
                self._pending_type = encoded_type.decode("ascii")
                self._pending_length = payload_length
            if len(self._buffer) < self._pending_length:
                break
            payload = bytes(self._buffer[: self._pending_length])
            del self._buffer[: self._pending_length]
            frame_type = self._pending_type
            self._pending_length = None
            frame = self._validate_frame(frame_type, payload)
            frames.append(frame)
            if self.terminal_type is not None and self._buffer:
                raise StreamProtocolError("data received after terminal frame")
        return frames

    def finish(self) -> None:
        if self._pending_length is not None:
            raise StreamProtocolError("truncated frame payload")
        if self._buffer:
            raise StreamProtocolError("truncated frame header")
        if self.terminal_type is None:
            raise StreamProtocolError("stream ended without E or X frame")

    def _validate_frame(self, frame_type: str, payload: bytes) -> StreamFrame:
        if self.metadata is None and frame_type != "M":
            raise StreamProtocolError("metadata must be the first frame")
        if frame_type == "M":
            if self.metadata is not None:
                raise StreamProtocolError("duplicate metadata frame")
            metadata = self._decode_json(payload, "metadata")
            self._validate_metadata(metadata)
            self.metadata = metadata
            return StreamFrame(frame_type, payload, metadata)
        if self.terminal_type is not None:
            raise StreamProtocolError("duplicate terminal frame")
        if frame_type == "A":
            if not payload:
                raise StreamProtocolError("audio frame must not be empty")
            block_align = int(self.metadata["channels"]) * 2
            if len(payload) % block_align:
                raise StreamProtocolError("audio frame is not sample-aligned")
            self.audio_frames += 1
            self.audio_bytes += len(payload)
            return StreamFrame(frame_type, payload)
        if frame_type == "E":
            end = self._decode_json(payload, "end")
            if self.audio_frames == 0:
                raise StreamProtocolError("successful stream contains no audio")
            expected_samples = self.audio_bytes // (int(self.metadata["channels"]) * 2)
            if end.get("total_samples") != expected_samples:
                raise StreamProtocolError("end total_samples does not match audio")
            if end.get("audio_frames") != self.audio_frames:
                raise StreamProtocolError("end audio_frames does not match audio")
            self.terminal_type = "E"
            return StreamFrame(frame_type, payload, end)
        error_payload = self._decode_json(payload, "error")
        if not isinstance(error_payload.get("code"), str) or not error_payload["code"]:
            raise StreamProtocolError("error frame requires a code")
        if not isinstance(error_payload.get("message"), str) or not error_payload["message"]:
            raise StreamProtocolError("error frame requires a message")
        self.terminal_type = "X"
        return StreamFrame(frame_type, payload, error_payload)

    @staticmethod
    def _decode_json(payload: bytes, label: str) -> dict[str, Any]:
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StreamProtocolError(f"{label} frame must contain UTF-8 JSON") from error
        if not isinstance(value, dict):
            raise StreamProtocolError(f"{label} frame must contain a JSON object")
        return value

    @staticmethod
    def _validate_metadata(metadata: dict[str, Any]) -> None:
        required = {
            "protocol": PROTOCOL_VERSION,
            "sample_format": "s16le",
            "bits_per_sample": 16,
            "channels": 1,
            "interleaved": True,
        }
        for key, expected in required.items():
            if metadata.get(key) != expected:
                raise StreamProtocolError(f"unsupported metadata field: {key}")
        sample_rate = metadata.get("sample_rate")
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
            raise StreamProtocolError("metadata sample_rate must be a positive integer")
