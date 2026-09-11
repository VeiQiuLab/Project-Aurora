import json
import struct

import pytest

from aurora_voice_node.stream_protocol import (
    MAX_FRAME_PAYLOAD,
    StreamFrameDecoder,
    StreamProtocolError,
    encode_frame,
    encode_json_frame,
    metadata_payload,
)


def complete_stream(audio=(b"\x00\x00" * 4, b"\x01\x00" * 3)):
    frames = [encode_json_frame("M", metadata_payload(sample_rate=24000))]
    frames.extend(encode_frame("A", chunk) for chunk in audio)
    frames.append(
        encode_json_frame(
            "E",
            {"total_samples": sum(map(len, audio)) // 2, "audio_frames": len(audio)},
        )
    )
    return b"".join(frames)


@pytest.mark.parametrize("boundary", [1, 2, 4, 5, 7, 31])
def test_decoder_handles_arbitrary_header_and_payload_boundaries(boundary):
    encoded = complete_stream()
    decoder = StreamFrameDecoder()
    frames = []
    for offset in range(0, len(encoded), boundary):
        frames.extend(decoder.feed(encoded[offset : offset + boundary]))
    decoder.finish()

    assert [frame.frame_type for frame in frames] == ["M", "A", "A", "E"]
    assert [frame.payload for frame in frames if frame.frame_type == "A"] == [
        b"\x00\x00" * 4,
        b"\x01\x00" * 3,
    ]


def test_metadata_must_be_first_and_unique():
    with pytest.raises(StreamProtocolError, match="metadata must be the first"):
        StreamFrameDecoder().feed(encode_frame("A", b"\0\0"))

    decoder = StreamFrameDecoder()
    decoder.feed(encode_json_frame("M", metadata_payload(sample_rate=24000)))
    with pytest.raises(StreamProtocolError, match="duplicate metadata"):
        decoder.feed(encode_json_frame("M", metadata_payload(sample_rate=24000)))


def test_error_frame_is_terminal_without_end():
    decoder = StreamFrameDecoder()
    frames = decoder.feed(
        encode_json_frame("M", metadata_payload(sample_rate=24000))
        + encode_json_frame("X", {"code": "upstream_failed", "message": "incomplete"})
    )
    decoder.finish()

    assert [frame.frame_type for frame in frames] == ["M", "X"]
    assert frames[-1].data["code"] == "upstream_failed"


def test_eof_without_end_or_error_is_rejected():
    decoder = StreamFrameDecoder()
    decoder.feed(encode_json_frame("M", metadata_payload(sample_rate=24000)))
    with pytest.raises(StreamProtocolError, match="without E or X"):
        decoder.finish()


def test_truncated_header_and_payload_are_rejected():
    header = StreamFrameDecoder()
    header.feed(b"M\x00")
    with pytest.raises(StreamProtocolError, match="truncated frame header"):
        header.finish()

    payload = StreamFrameDecoder()
    payload.feed(struct.pack(">cI", b"M", 10) + b"{}")
    with pytest.raises(StreamProtocolError, match="truncated frame payload"):
        payload.finish()


def test_oversized_frame_is_rejected_before_payload_arrives():
    decoder = StreamFrameDecoder()
    with pytest.raises(StreamProtocolError, match="exceeds 64 KiB"):
        decoder.feed(struct.pack(">cI", b"M", MAX_FRAME_PAYLOAD + 1))


def test_unaligned_pcm_and_zero_audio_are_rejected():
    prefix = encode_json_frame("M", metadata_payload(sample_rate=24000))
    with pytest.raises(StreamProtocolError, match="sample-aligned"):
        StreamFrameDecoder().feed(prefix + encode_frame("A", b"\x00"))

    decoder = StreamFrameDecoder()
    with pytest.raises(StreamProtocolError, match="contains no audio"):
        decoder.feed(prefix + encode_json_frame("E", {"total_samples": 0, "audio_frames": 0}))


def test_end_counts_must_match_received_audio():
    decoder = StreamFrameDecoder()
    encoded = (
        encode_json_frame("M", metadata_payload(sample_rate=24000))
        + encode_frame("A", b"\0\0" * 2)
        + encode_json_frame("E", {"total_samples": 99, "audio_frames": 1})
    )
    with pytest.raises(StreamProtocolError, match="total_samples"):
        decoder.feed(encoded)


def test_json_frames_are_compact_utf8():
    encoded = encode_json_frame("X", {"code": "错误", "message": "失败"})
    payload = encoded[5:]
    assert json.loads(payload.decode("utf-8"))["message"] == "失败"
