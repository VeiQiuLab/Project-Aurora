import struct

import pytest

from aurora_voice_node.wav_utils import (
    WAVE_FORMAT_IEEE_FLOAT,
    WAVE_FORMAT_PCM,
    inspect_wav,
    normalize_to_pcm16_wav,
)
from wav_helpers import make_wav


def make_float_wav(samples, *, channels=1, sample_rate=24000):
    data = struct.pack("<" + "f" * len(samples), *samples)
    block_align = channels * 4
    fmt = struct.pack(
        "<HHIIHH",
        WAVE_FORMAT_IEEE_FLOAT,
        channels,
        sample_rate,
        sample_rate * block_align,
        block_align,
        32,
    )
    riff_size = 4 + 8 + len(fmt) + 8 + len(data)
    return b"RIFF" + struct.pack("<I", riff_size) + b"WAVEfmt " + struct.pack(
        "<I", len(fmt)
    ) + fmt + b"data" + struct.pack("<I", len(data)) + data


def pcm_samples(data):
    info = inspect_wav(data)
    return info, list(struct.unpack_from("<" + "h" * (info.data_size // 2), data, info.data_offset))


def test_pcm16_wav_passes_through_unchanged():
    source = make_wav(frames=3, sample_rate=22050)

    actual = normalize_to_pcm16_wav(source)

    assert actual == source
    info = inspect_wav(actual)
    assert info.format_tag == WAVE_FORMAT_PCM
    assert info.bits_per_sample == 16
    assert info.sample_rate == 22050
    assert info.channels == 1


def test_float32_wav_becomes_pcm16_preserving_stream_shape():
    source = make_float_wav((-1.0, 0.0, 1.0, 0.5), channels=2, sample_rate=48000)

    actual = normalize_to_pcm16_wav(source)

    info, samples = pcm_samples(actual)
    assert info.format_tag == WAVE_FORMAT_PCM
    assert info.bits_per_sample == 16
    assert info.channels == 2
    assert info.sample_rate == 48000
    assert samples == [-32768, 0, 32767, 16384]
    assert actual[:4] == b"RIFF"
    assert actual[8:12] == b"WAVE"


def test_float_samples_are_clamped_without_int16_wraparound():
    source = make_float_wav((-2.0, -1.0, 0.0, 1.0, 2.0, float("nan"), float("inf")))

    _, samples = pcm_samples(normalize_to_pcm16_wav(source))

    assert samples == [-32768, -32768, 0, 32767, 32767, 0, 0]


@pytest.mark.parametrize(
    "source",
    [
        b"not a WAV",
        b"RIFF\x04\x00\x00\x00WAVE",
        make_float_wav((0.0,))[:-1],
        make_float_wav((0.0,))[:12] + b"fmt " + struct.pack("<I", 16) + b"\x00" * 4,
    ],
)
def test_invalid_or_truncated_wav_is_rejected(source):
    with pytest.raises(ValueError):
        normalize_to_pcm16_wav(source)


def test_unsupported_wav_format_is_rejected():
    source = bytearray(make_float_wav((0.0,)))
    struct.pack_into("<H", source, 20, 6)

    with pytest.raises(ValueError, match="unsupported WAV format tag: 6"):
        normalize_to_pcm16_wav(bytes(source))
