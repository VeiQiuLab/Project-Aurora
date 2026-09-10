import io
import struct
import wave


def make_wav(*, frames: int = 240, sample_rate: int = 24000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00\x00" * frames)
    return output.getvalue()


def make_float_wav(samples, *, channels: int = 1, sample_rate: int = 24000) -> bytes:
    data = struct.pack("<" + "f" * len(samples), *samples)
    block_align = channels * 4
    fmt = struct.pack(
        "<HHIIHH",
        3,
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
