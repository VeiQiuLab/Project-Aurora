"""Self-contained WAV normalization for Voice Node deployment."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass


WAVE_FORMAT_PCM = 1
WAVE_FORMAT_IEEE_FLOAT = 3


@dataclass(frozen=True)
class WavInfo:
    format_tag: int
    channels: int
    sample_rate: int
    bits_per_sample: int
    data_offset: int
    data_size: int


def normalize_to_pcm16_wav(data: bytes) -> bytes:
    """Return a standards-compliant PCM16 WAV, converting IEEE Float32 as needed."""

    info = _parse_wav(data)
    if info.format_tag == WAVE_FORMAT_PCM:
        if info.bits_per_sample != 16:
            raise ValueError("only PCM16 WAV audio is supported")
        return data
    if info.format_tag != WAVE_FORMAT_IEEE_FLOAT or info.bits_per_sample != 32:
        raise ValueError(f"unsupported WAV format tag: {info.format_tag}")

    pcm = bytearray(info.data_size // 2)
    for source_offset, target_offset in zip(
        range(info.data_offset, info.data_offset + info.data_size, 4),
        range(0, len(pcm), 2),
    ):
        sample = struct.unpack_from("<f", data, source_offset)[0]
        struct.pack_into("<h", pcm, target_offset, _float_to_pcm16(sample))

    block_align = info.channels * 2
    fmt_chunk = struct.pack(
        "<HHIIHH",
        WAVE_FORMAT_PCM,
        info.channels,
        info.sample_rate,
        info.sample_rate * block_align,
        block_align,
        16,
    )
    riff_size = 4 + 8 + len(fmt_chunk) + 8 + len(pcm)
    return b"RIFF" + struct.pack("<I", riff_size) + b"WAVE" + b"fmt " + struct.pack(
        "<I", len(fmt_chunk)
    ) + fmt_chunk + b"data" + struct.pack("<I", len(pcm)) + bytes(pcm)


def inspect_wav(data: bytes) -> WavInfo:
    """Return PCM16 WAV metadata, raising ValueError for unusable audio."""

    info = _parse_wav(data)
    if info.format_tag != WAVE_FORMAT_PCM or info.bits_per_sample != 16:
        raise ValueError("WAV is not PCM16")
    return info


def _parse_wav(data: bytes) -> WavInfo:
    if not isinstance(data, bytes) or len(data) < 12:
        raise ValueError("WAV response is too short")
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("response is not a RIFF/WAVE file")

    declared_size = struct.unpack_from("<I", data, 4)[0]
    riff_end = declared_size + 8
    if riff_end != len(data):
        raise ValueError("invalid RIFF chunk size")

    fmt_chunk: bytes | None = None
    data_offset: int | None = None
    data_size: int | None = None
    offset = 12
    while offset < riff_end:
        if riff_end - offset < 8:
            raise ValueError("truncated WAV chunk header")
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        chunk_data_offset = offset + 8
        chunk_end = chunk_data_offset + chunk_size
        padded_end = chunk_end + (chunk_size & 1)
        if chunk_end > riff_end or padded_end > riff_end:
            raise ValueError("truncated WAV chunk data")
        if chunk_id == b"fmt " and fmt_chunk is None:
            fmt_chunk = data[chunk_data_offset:chunk_end]
        elif chunk_id == b"data" and data_offset is None:
            data_offset = chunk_data_offset
            data_size = chunk_size
        offset = padded_end

    if fmt_chunk is None or data_offset is None or data_size is None:
        raise ValueError("WAV must contain fmt and data chunks")
    if len(fmt_chunk) < 16:
        raise ValueError("truncated fmt chunk")

    format_tag, channels, sample_rate, byte_rate, block_align, bits_per_sample = struct.unpack_from(
        "<HHIIHH", fmt_chunk
    )
    if channels <= 0 or sample_rate <= 0:
        raise ValueError("WAV contains invalid channel count or sample rate")
    if format_tag == WAVE_FORMAT_PCM:
        expected_width = bits_per_sample // 8
        if bits_per_sample != 16 or block_align != channels * expected_width:
            raise ValueError("invalid PCM16 fmt chunk")
    elif format_tag == WAVE_FORMAT_IEEE_FLOAT:
        if bits_per_sample != 32 or block_align != channels * 4:
            raise ValueError("invalid IEEE Float32 fmt chunk")
    else:
        raise ValueError(f"unsupported WAV format tag: {format_tag}")
    if byte_rate != sample_rate * block_align:
        raise ValueError("invalid WAV byte rate")
    if data_size == 0 or data_size % block_align:
        raise ValueError("WAV contains incomplete audio frames")

    return WavInfo(
        format_tag=format_tag,
        channels=channels,
        sample_rate=sample_rate,
        bits_per_sample=bits_per_sample,
        data_offset=data_offset,
        data_size=data_size,
    )


def _float_to_pcm16(sample: float) -> int:
    if not math.isfinite(sample):
        return 0
    if sample <= -1.0:
        return -32768
    if sample >= 1.0:
        return 32767
    return int(round(sample * 32767.0))
