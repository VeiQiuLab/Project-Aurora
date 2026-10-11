"""WAV engineering guards for the opt-in benchmark; no model is required."""
import importlib.util
import struct
import wave
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "sherpa_melo_probe", Path(__file__).resolve().parents[1] / "scripts/probe_sherpa_melo.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_wav(path, *, channels=1, width=2, silent=False):
    with wave.open(str(path), "wb") as wav:
        wav.setparams((channels, width, 44100, 0, "NONE", "not compressed"))
        wav.writeframes((b"\x00\x00" if silent else struct.pack("<h", 4000)) * 4410)


def test_valid_melo_pcm_is_fully_decoded(tmp_path):
    path = tmp_path / "audio.wav"
    make_wav(path)
    result = MODULE.inspect_pcm(path)
    assert result["sample_rate"] == 44100
    assert result["channels"] == 1
    assert result["audio_seconds"] == .1
    assert result["pcm_rms"] > .1
    assert len(result["sha256"]) == 64


@pytest.mark.parametrize("kind", ["silent", "channels", "width", "truncated", "signature", "size"])
def test_invalid_or_silent_wav_is_rejected(tmp_path, kind):
    path = tmp_path / "invalid.wav"
    make_wav(path, silent=kind == "silent", channels=2 if kind == "channels" else 1,
             width=1 if kind == "width" else 2)
    data = path.read_bytes()
    if kind == "truncated":
        data = data[:-2]
        data = data[:4] + struct.pack("<I", len(data)-8) + data[8:]
    elif kind == "signature":
        data = b"FAIL" + data[4:]
    elif kind == "size":
        data = data[:4] + struct.pack("<I", 12) + data[8:]
    path.write_bytes(data)
    with pytest.raises(ValueError):
        MODULE.inspect_pcm(path)


def test_fixed_texts_match_previous_stage():
    old_spec = importlib.util.spec_from_file_location(
        "old_probe_constants", Path(__file__).resolve().parents[1] / "scripts/probe_local_cosyvoice.py")
    old = importlib.util.module_from_spec(old_spec)
    old_spec.loader.exec_module(old)
    assert MODULE.TEXTS == old.TEXTS
    assert [len(MODULE.TEXTS[i]) for i in [0, 2, 3]] == [16, 52, 109]
